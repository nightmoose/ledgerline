"""Deterministic evidence reader. It can lower confidence and cannot move money."""

from __future__ import annotations

import re

_CONTRADICTION = re.compile(
    r"slip|next week|delay|won't arrive|will not arrive|cannot pay|can't pay|hold the payment",
    re.IGNORECASE,
)


def read_evidence(text: str) -> dict[str, object]:
    contradicts = bool(_CONTRADICTION.search(text or ""))
    if contradicts:
        explanation = 'Read customer email: "payment will slip to next week" → contradicts forecast'
    else:
        explanation = "No contradiction in the evidence."
    return {"contradicts": contradicts, "explanation": explanation, "provider": "offline"}
