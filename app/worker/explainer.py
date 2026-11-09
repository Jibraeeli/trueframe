"""Turn a score into a plain-English summary.

This is a plug-in. Stage 1 fills in a template. Stage 4 adds a class with the
same explain method that calls an AI model, and nothing else has to change.
"""

from typing import Protocol

from app.worker.scoring import LOWERS, RAISES, Score

_OPENINGS = {
    "likely_manipulated": "This file shows strong signs of being AI-generated or manipulated.",
    "inconclusive": "The checks could not reach a clear answer for this file.",
    "no_signs_found": "The checks found no signs of manipulation in this file.",
}

_CLOSINGS = {
    "likely_manipulated": "Treat it with caution and look for the original source.",
    "inconclusive": "Check where it came from before relying on it.",
    "no_signs_found": "This is not proof that it is genuine, as detection can miss new techniques.",
}


class Explainer(Protocol):
    def explain(self, score: Score) -> str: ...


class TemplateExplainer:
    def explain(self, score: Score) -> str:
        against = [e.detail for e in score.evidence if e.effect == LOWERS]
        supporting = [e.detail for e in score.evidence if e.effect == RAISES]

        parts = [_OPENINGS[score.verdict]]
        if against:
            parts.append("Reasons for concern: " + " ".join(against))
        if supporting:
            parts.append("In its favour: " + " ".join(supporting))
        parts.append(_CLOSINGS[score.verdict])
        return " ".join(parts)
