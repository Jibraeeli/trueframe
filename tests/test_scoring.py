import pytest

from app.worker.explainer import TemplateExplainer
from app.worker.metadata import MetadataResult
from app.worker.provenance import INVALID, NONE, SIGNED_UNTRUSTED, TRUSTED, ProvenanceResult
from app.worker.scoring import aggregate_probabilities, combine

NO_CREDENTIALS = ProvenanceResult(NONE, "No content credentials.")
CLEAN_METADATA = MetadataResult()


def provenance(status, ai_generated=False):
    return ProvenanceResult(status, "note", ai_generated, "Example Issuer")


def test_top_third_is_averaged_so_a_short_fake_section_is_not_hidden():
    probabilities = [0.9, 0.9, 0.1, 0.1, 0.1, 0.1]
    assert aggregate_probabilities(probabilities) == pytest.approx(0.9)


def test_single_image_uses_its_own_probability():
    assert aggregate_probabilities([0.42]) == pytest.approx(0.42)


@pytest.mark.parametrize(
    ("probability", "score", "verdict"),
    [
        (0.0, 100, "no_signs_found"),
        (0.30, 70, "no_signs_found"),
        (0.31, 69, "inconclusive"),
        (0.60, 40, "inconclusive"),
        (0.61, 39, "likely_manipulated"),
        (1.0, 0, "likely_manipulated"),
    ],
)
def test_verdict_bands(probability, score, verdict):
    result = combine(probability, 1, NO_CREDENTIALS, CLEAN_METADATA)
    assert (result.trust_score, result.verdict) == (score, verdict)


def test_trusted_signature_raises_score():
    assert combine(0.5, 1, provenance(TRUSTED), CLEAN_METADATA).trust_score == 65


def test_untrusted_signature_earns_nothing():
    assert combine(0.5, 1, provenance(SIGNED_UNTRUSTED), CLEAN_METADATA).trust_score == 50


def test_failed_signature_lowers_score():
    assert combine(0.5, 1, provenance(INVALID), CLEAN_METADATA).trust_score == 25


def test_declared_ai_caps_score_even_if_detector_is_fooled():
    result = combine(0.01, 1, provenance(SIGNED_UNTRUSTED, ai_generated=True), CLEAN_METADATA)
    assert result.trust_score == 10
    assert result.verdict == "likely_manipulated"


def test_ai_tool_in_metadata_caps_score():
    metadata = MetadataResult(ai_tools=["Midjourney"])
    assert combine(0.01, 1, NO_CREDENTIALS, metadata).trust_score == 15


def test_editing_software_is_not_penalised():
    metadata = MetadataResult(editors=["Adobe Photoshop"])
    assert combine(0.1, 1, NO_CREDENTIALS, metadata).trust_score == 90


def test_score_stays_within_range():
    assert combine(0.0, 1, provenance(TRUSTED), CLEAN_METADATA).trust_score == 100
    assert combine(1.0, 1, provenance(INVALID), CLEAN_METADATA).trust_score == 0


def test_summary_never_claims_a_file_is_genuine():
    score = combine(0.05, 1, NO_CREDENTIALS, CLEAN_METADATA)
    summary = TemplateExplainer().explain(score)
    assert "not proof" in summary
