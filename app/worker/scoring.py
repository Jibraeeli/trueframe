"""Check 4: combine the signals into one 0 to 100 trust score.

The detector sets the starting score. Provenance and metadata then adjust it,
because a signed statement in the file can be stronger than a model's guess.
This module has no dependencies, so every rule can be unit tested.
"""

import math
from dataclasses import dataclass, field

from app.worker.metadata import MetadataResult
from app.worker.provenance import INVALID, TRUSTED, ProvenanceResult

LIKELY_MANIPULATED_BELOW = 40
NO_SIGNS_FROM = 70

TRUSTED_SIGNATURE_BONUS = 15
INVALID_SIGNATURE_PENALTY = 25
DECLARED_AI_SCORE_CAP = 10
AI_TOOL_METADATA_SCORE_CAP = 15

HIGH_FAKE_PROBABILITY = 0.7
LOW_FAKE_PROBABILITY = 0.3

RAISES = "raises"
LOWERS = "lowers"
NEUTRAL = "neutral"


@dataclass(frozen=True)
class Evidence:
    signal: str
    effect: str
    detail: str


@dataclass
class Score:
    trust_score: int
    verdict: str
    verdict_label: str
    evidence: list[Evidence] = field(default_factory=list)


def aggregate_probabilities(probabilities: list[float]) -> float:
    """Average the most suspicious third of the frames.

    A plain average would let a short faked section hide among normal frames.
    """
    ordered = sorted(probabilities, reverse=True)
    top = ordered[: math.ceil(len(ordered) / 3)]
    return sum(top) / len(top)


def _verdict(trust_score: int) -> tuple[str, str]:
    if trust_score < LIKELY_MANIPULATED_BELOW:
        return "likely_manipulated", "Likely AI-generated or manipulated"
    if trust_score < NO_SIGNS_FROM:
        return "inconclusive", "Inconclusive"
    return "no_signs_found", "No signs of manipulation found"


def _detector_evidence(probability: float, frames: int) -> Evidence:
    percent = round(probability * 100)
    sampled = "1 image" if frames == 1 else f"{frames} frames"
    if probability >= HIGH_FAKE_PROBABILITY:
        effect = LOWERS
    elif probability <= LOW_FAKE_PROBABILITY:
        effect = RAISES
    else:
        effect = NEUTRAL
    return Evidence("Detection model", effect, f"Rated {percent}% likely fake across {sampled}.")


def combine(
    fake_probability: float,
    frames_analysed: int,
    provenance: ProvenanceResult,
    metadata: MetadataResult,
) -> Score:
    score = round(100 * (1 - fake_probability))
    evidence = [_detector_evidence(fake_probability, frames_analysed)]

    if provenance.ai_generated:
        score = min(score, DECLARED_AI_SCORE_CAP)
        evidence.append(
            Evidence("Content credentials", LOWERS, "The file's credentials declare it AI-generated.")
        )
    elif provenance.status == TRUSTED:
        score += TRUSTED_SIGNATURE_BONUS
        evidence.append(
            Evidence("Content credentials", RAISES, f"Validly signed by {provenance.issuer}.")
        )
    elif provenance.status == INVALID:
        score -= INVALID_SIGNATURE_PENALTY
        evidence.append(
            Evidence(
                "Content credentials",
                LOWERS,
                "The file has credentials, but they failed validation. It may have been altered.",
            )
        )
    else:
        evidence.append(Evidence("Content credentials", NEUTRAL, provenance.note))

    if metadata.ai_tools:
        score = min(score, AI_TOOL_METADATA_SCORE_CAP)
        names = ", ".join(metadata.ai_tools)
        evidence.append(Evidence("Metadata", LOWERS, f"Metadata names AI tools: {names}."))
    elif metadata.editors:
        names = ", ".join(metadata.editors)
        evidence.append(
            Evidence("Metadata", NEUTRAL, f"Processed with {names}. Common for genuine media too.")
        )
    else:
        evidence.append(Evidence("Metadata", NEUTRAL, "No AI tool or editing software named."))

    score = max(0, min(100, score))
    verdict, label = _verdict(score)
    return Score(score, verdict, label, evidence)
