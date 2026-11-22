"""The style rules (resources/rules.json): which frames suit which faces, and why."""
from __future__ import annotations

import json
from dataclasses import dataclass

from tryon.config import RESOURCES_DIR


@dataclass(frozen=True)
class Rules:
    raw: dict

    @property
    def face_shapes(self) -> dict:
        return self.raw["face_shapes"]

    @property
    def frame_shapes(self) -> dict:
        return self.raw["frame_shapes"]

    @property
    def weights(self) -> dict:
        return self.raw["weights"]

    def frame_score(self, face: str, frame: str) -> float:
        return float(self.face_shapes[face]["frames"].get(frame, 0.4))     # unknown frame shapes are neutral-low

    def pairing(self, face: str, frame: str) -> str:
        return self.raw["pairings"].get(face, {}).get(frame, "")

    def label_for(self, percent: int) -> str:
        for rule in sorted(self.raw["labels"], key=lambda r: -r["min"]):
            if percent >= rule["min"]:
                return rule["label"]
        return ""


def load_rules() -> Rules:
    raw = json.loads((RESOURCES_DIR / "rules.json").read_text(encoding="utf-8"))
    for face, spec in raw["face_shapes"].items():
        unknown = set(spec["frames"]) - set(raw["frame_shapes"])
        if unknown:
            raise ValueError(f"rules.json: face shape '{face}' scores unknown frame shapes {sorted(unknown)}")
    return Rules(raw)
