"""Plain-language descriptions of a face and the reasons a frame was recommended."""
from __future__ import annotations

# (min, max) typical range per measurement, used to place a marker on a gauge in the UI
_RANGES = {"length": (1.00, 1.45), "jaw": (0.60, 0.95), "forehead": (0.85, 1.40), "chin": (85.0, 120.0)}


def _pos(key: str, value: float) -> float:
    lo, hi = _RANGES[key]
    return round(min(1.0, max(0.0, (value - lo) / (hi - lo))), 3)


def describe_face(m: dict[str, float]) -> list[dict]:
    """The four measurements behind the face shape, each with a short note and a 0-1 gauge position."""
    L, J, F, A = m["length_cheek"], m["jaw_cheek"], m["fore_jaw"], m["chin_angle"]
    return [
        {"key": "length", "label": "Face length", "value": f"{L:.2f}× width", "position": _pos("length", L),
         "note": "About as long as it is wide" if L < 1.12 else "Slightly longer than wide" if L < 1.28 else "Noticeably longer than wide"},
        {"key": "jaw", "label": "Jaw width", "value": f"{J:.0%} of cheekbones", "position": _pos("jaw", J),
         "note": "Broad, strong jaw" if J > 0.82 else "Narrow jaw" if J < 0.72 else "Softly defined jaw"},
        {"key": "forehead", "label": "Forehead", "value": f"{F:.2f}× jaw", "position": _pos("forehead", F),
         "note": "Wider than the jaw" if F > 1.18 else "Close to the jaw's width" if F < 0.98 else "Balanced with the jaw"},
        {"key": "chin", "label": "Chin angle", "value": f"{A:.0f}°", "position": _pos("chin", A),
         "note": "Soft, rounded chin" if A > 110 else "Pointed chin" if A < 96 else "Gently defined chin"},
    ]


def personal_note(face: str, m: dict[str, float]) -> str:
    """One sentence tying the recommendation to this person's own measurements."""
    L, J, F = m["length_cheek"], m["jaw_cheek"], m["fore_jaw"]
    return {
        "oval": f"Your face is {L:.2f}× as long as it is wide, a balanced ratio that suits most frames.",
        "round": f"Your face is only {L:.2f}× as long as it is wide, so frames that add length or definition help.",
        "square": f"Your jaw is {J:.0%} as wide as your cheekbones, so curved lenses soften the lower face.",
        "heart": f"Your forehead is {F:.2f}× as wide as your jaw, so balance comes from the lower half of the frame.",
        "oblong": f"Your face is {L:.2f}× as long as it is wide, so deeper, wider frames add balance.",
    }.get(face, "")


def proportion_note(label: str | None) -> str:
    return {
        "balanced": "The lens depth is well matched to the length of your face.",
        "deep": "This frame is deeper than average for your face, so it gives a bolder look.",
        "slim": "This frame is slimmer than average for your face, so it gives a lighter look.",
    }.get(label or "", "")
