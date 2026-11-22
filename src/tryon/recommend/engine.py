"""Score and rank frames for a face.

    match % = 85% shape harmony + 15% proportions        (weights live in rules.json)

  * shape harmony: how well the frame shape suits the face shape (rules.json). When the detector is unsure
    it gives a probability for every face shape and the score is the probability-weighted average, so a face
    that sits between oval and oblong is matched to frames that flatter both.
  * proportions: how close the frame's depth is to what suits the length of this face (a heuristic).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from tryon.catalog.store import Product
from tryon.recommend import explain
from tryon.recommend.rules import Rules
from tryon.vision.face_shape import SHAPES

TOP_PICKS = 6
ADULT = ("men", "women", "unisex")
_IDEAL_ASPECT_K = 3.5          # ideal frame width/height = K / (face length / face width)


@dataclass(frozen=True)
class FaceProfile:
    probabilities: dict[str, float]               # over all five face shapes, sums to 1
    measurements: dict[str, float] | None = None
    overridden: bool = False                      # True when the person chose the shape themselves

    @property
    def primary(self) -> str:
        return max(self.probabilities, key=self.probabilities.get)


def make_profile(shape: str | None = None, probabilities: dict[str, float] | None = None,
                 measurements: dict[str, float] | None = None, overridden: bool = False) -> FaceProfile:
    """`overridden` (or no probabilities) means the shape is certain: all the weight goes on `shape`."""
    if shape not in SHAPES and not probabilities:
        raise ValueError(f"Unknown face shape: {shape!r}")
    if overridden or not probabilities:
        return FaceProfile({s: 1.0 if s == shape else 0.0 for s in SHAPES}, measurements, overridden)
    total = sum(max(probabilities.get(s, 0.0), 0.0) for s in SHAPES) or 1.0
    return FaceProfile({s: max(probabilities.get(s, 0.0), 0.0) / total for s in SHAPES}, measurements, False)


def proportion_fit(aspect: float, length_cheek: float | None) -> tuple[float, str | None]:
    """(score 0-1, 'balanced' | 'deep' | 'slim'). Longer faces suit deeper frames, shorter faces slimmer ones."""
    if not length_cheek:
        return 0.8, None
    ratio = aspect / (_IDEAL_ASPECT_K / length_cheek)
    z = math.log(ratio) / 0.22
    return math.exp(-0.5 * z * z), ("slim" if ratio > 1.2 else "deep" if ratio < 1 / 1.2 else "balanced")


@dataclass
class Match:
    product: Product
    percent: int
    label: str
    shape_score: float
    proportion_score: float
    proportion_label: str | None
    reasons: list[str]
    top_pick: bool = False


def _reasons(rules: Rules, profile: FaceProfile, p: Product, shape_label: str | None) -> list[str]:
    face = profile.primary
    out = []
    if (s := rules.pairing(face, p.frame_shape)):
        out.append(s)
    if profile.measurements and not profile.overridden and (s := explain.personal_note(face, profile.measurements)):
        out.append(s)
    ranked = sorted(profile.probabilities.items(), key=lambda t: -t[1])
    (a, pa), (b, pb) = ranked[0], ranked[1]
    if not profile.overridden and pa < 0.7 and pb >= 0.25 and min(rules.frame_score(a, p.frame_shape), rules.frame_score(b, p.frame_shape)) >= 0.7:
        out.append(f"Your face sits between {a} and {b}, and this style flatters both.")
    if (s := explain.proportion_note(shape_label)):
        out.append(s)
    return out[:3]


def score_product(rules: Rules, profile: FaceProfile, p: Product) -> Match:
    shape = sum(prob * rules.frame_score(face, p.frame_shape) for face, prob in profile.probabilities.items())
    length = profile.measurements.get("length_cheek") if profile.measurements else None
    prop, prop_label = proportion_fit(p.aspect, length)
    w = rules.weights
    final = (w["shape"] * shape + w["proportion"] * prop) / (w["shape"] + w["proportion"])
    percent = max(35, min(98, round(final * 98)))       # never promise 100%
    return Match(p, percent, rules.label_for(percent), shape, prop, prop_label, [])


def audience_ok(p: Product, audience: str) -> bool:
    if audience == "kids":
        return p.audience == "kids"
    if audience in ("men", "women"):
        return p.audience in (audience, "unisex")
    return p.audience in ADULT                    # "all" = every adult frame (kids' frames stay out)


def _interleave_ties(pool: list[Match]) -> list[Match]:
    """Keep strict best-first order by match %; among frames with the very same %, alternate frame shapes."""
    out: list[Match] = []
    i = 0
    while i < len(pool):
        j = i
        while j < len(pool) and pool[j].percent == pool[i].percent:
            j += 1
        queues: dict[str, list[Match]] = {}
        for m in pool[i:j]:
            queues.setdefault(m.product.frame_shape, []).append(m)
        while any(queues.values()):
            for shape in list(queues):
                if queues[shape]:
                    out.append(queues[shape].pop(0))
        i = j
    return out


def recommend(rules: Rules, products: tuple[Product, ...], profile: FaceProfile, *, audience: str = "all",
              frame_shapes: set[str] | None = None, colors: set[str] | None = None) -> list[Match]:
    """All matching products, best match first. The first TOP_PICKS are flagged as the headline picks."""
    pool = [score_product(rules, profile, p) for p in products
            if audience_ok(p, audience) and (not frame_shapes or p.frame_shape in frame_shapes)
            and (not colors or p.color_name in colors)]
    pool.sort(key=lambda m: (-m.percent, -m.proportion_score, m.product.sku))
    ordered = _interleave_ties(pool)
    picks = min(TOP_PICKS, len(ordered))
    for i, m in enumerate(ordered):
        m.top_pick = i < picks
        m.reasons = _reasons(rules, profile, m.product, m.proportion_label)
    return ordered


def summarise_styles(rules: Rules, matches: list[Match]) -> list[dict]:
    """For each frame style: how many frames and the best match %, best style first."""
    best: dict[str, dict] = {}
    for m in matches:                                       # matches arrive best-first
        s = best.setdefault(m.product.frame_shape, {"shape": m.product.frame_shape, "count": 0, "best_percent": m.percent})
        s["count"] += 1
    for s in best.values():
        s["label"] = rules.frame_shapes.get(s["shape"], {}).get("label", s["shape"].title())
    return sorted(best.values(), key=lambda s: (-s["best_percent"], s["label"]))
