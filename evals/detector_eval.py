"""Measures the detector on labelled public images.

Each image goes through the real model and the real scoring rule, with no
provenance or metadata to help, so these are the verdicts the detector earns
alone. Every image is one single picture. Video reports average several frames,
which this does not measure.

Usage: python -m evals.detector_eval --data /data --out /out/detector.json
"""

import argparse
import json
import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pyarrow.parquet as pq

from app.worker.detector import OnnxDetector
from app.worker.metadata import MetadataResult
from app.worker.provenance import NONE, ProvenanceResult
from app.worker.scoring import combine

FAKE = "fake"
REAL = "real"
CAUGHT = "likely_manipulated"
CLEARED = "no_signs_found"
SEED = 20261110
PROGRESS_EVERY = 100
Z_95 = 1.96


def label_from_column(names: dict[int, str]) -> Callable[[dict], str | None]:
    return lambda row: names[row["label"]]


def label_from_filename(row: dict) -> str | None:
    """Only names that say 'swap' are labelled. The rest are left out."""
    return FAKE if "swap" in row["image"]["path"] else None


@dataclass(frozen=True)
class Source:
    name: str
    folder: str
    what: str
    columns: tuple[str, ...]
    label: Callable[[dict], str | None]


SOURCES = [
    Source(
        "stylegan",
        "stylegan",
        "Fully AI-generated faces (StyleGAN) against real photos",
        ("image", "label"),
        label_from_column({0: REAL, 1: FAKE}),
    ),
    Source(
        "celebdf",
        "celebdf",
        "Frames from manipulated celebrity videos against real ones",
        ("image", "label"),
        label_from_column({0: FAKE, 1: REAL}),
    ),
    Source(
        "faceswap",
        "faceswap",
        "Face-swapped images, fakes only, labelled from file names",
        ("filename", "image"),
        label_from_filename,
    ),
]


def wilson(hits: int, total: int) -> tuple[float, float]:
    """95% range for a rate. It stays sensible on small samples and near 0%."""
    if not total:
        return 0.0, 0.0
    rate = hits / total
    z2 = Z_95**2
    centre = (rate + z2 / (2 * total)) / (1 + z2 / total)
    margin = (Z_95 / (1 + z2 / total)) * math.sqrt(
        rate * (1 - rate) / total + z2 / (4 * total**2)
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def auc(fake_scores: list[float], real_scores: list[float]) -> float | None:
    """Chance that a random fake is rated more suspicious than a random real."""
    if not fake_scores or not real_scores:
        return None
    combined = np.array(fake_scores + real_scores)
    _, inverse, counts = np.unique(combined, return_inverse=True, return_counts=True)
    cumulative = np.cumsum(counts)
    # Tied scores share the average of the ranks they cover.
    average_rank = cumulative - (counts - 1) / 2
    fake_rank_sum = average_rank[inverse][: len(fake_scores)].sum()
    fakes, reals = len(fake_scores), len(real_scores)
    return float((fake_rank_sum - fakes * (fakes + 1) / 2) / (fakes * reals))


def verdict(probability: float) -> str:
    return combine(probability, 1, ProvenanceResult(NONE, ""), MetadataResult()).verdict


def share(verdicts: list[str], wanted: str) -> dict:
    hits = sum(item == wanted for item in verdicts)
    low, high = wilson(hits, len(verdicts))
    return {
        "count": hits,
        "rate": round(hits / len(verdicts), 4) if verdicts else None,
        "low_95": round(low, 4),
        "high_95": round(high, 4),
    }


def choose(labels: list[str | None], per_class: int) -> list[int]:
    """Pick the same random rows every run, up to the limit for each class."""
    rng = np.random.default_rng(SEED)
    picked: list[int] = []
    for wanted in (FAKE, REAL):
        rows = [index for index, label in enumerate(labels) if label == wanted]
        rng.shuffle(rows)
        picked += rows[:per_class]
    return sorted(int(index) for index in picked)


def evaluate(source: Source, data: Path, detector: OnnxDetector, per_class: int) -> dict:
    files = sorted((data / source.folder).glob("*.parquet"))
    table = pq.read_table(files, columns=list(source.columns))
    labels = [source.label(row) for row in table.to_pylist()]
    picked = choose(labels, per_class)
    subset = table.take(picked)
    print(f"{source.name}: {len(picked)} images", flush=True)

    probabilities: dict[str, list[float]] = {FAKE: [], REAL: []}
    unreadable = 0
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "image"
        for number, (row_index, row) in enumerate(zip(picked, subset.to_pylist()), start=1):
            path.write_bytes(row["image"]["bytes"])
            try:
                probabilities[labels[row_index]].append(detector.fake_probability(path))
            except (OSError, ValueError):
                unreadable += 1
            if number % PROGRESS_EVERY == 0:
                print(f"  {number}/{len(picked)}", flush=True)

    fakes, reals = probabilities[FAKE], probabilities[REAL]
    fake_verdicts = [verdict(value) for value in fakes]
    real_verdicts = [verdict(value) for value in reals]
    score = auc(fakes, reals)
    return {
        "what": source.what,
        "fakes": len(fakes),
        "reals": len(reals),
        "unreadable": unreadable,
        "auc": round(score, 4) if score is not None else None,
        "fakes_flagged": share(fake_verdicts, CAUGHT),
        "fakes_given_all_clear": share(fake_verdicts, CLEARED),
        "reals_wrongly_flagged": share(real_verdicts, CAUGHT),
        "reals_given_all_clear": share(real_verdicts, CLEARED),
        "seconds": round(time.monotonic() - started),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-class", type=int, default=500)
    args = parser.parse_args()

    detector = OnnxDetector(os.environ["MODEL_PATH"])
    results = {
        "model": detector.name,
        "per_class_limit": args.per_class,
        "seed": SEED,
        "datasets": {},
    }
    for source in SOURCES:
        results["datasets"][source.name] = evaluate(source, args.data, detector, args.per_class)
        args.out.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
