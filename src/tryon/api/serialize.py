"""Turn domain objects into the JSON the web page uses."""
from __future__ import annotations

from tryon.catalog.store import Catalog, Product
from tryon.recommend import explain
from tryon.recommend.engine import FaceProfile, Match, summarise_styles
from tryon.recommend.rules import Rules
from tryon.vision.face_shape import FaceAnalysis


def media(path: str, version: str) -> str:
    return f"/media/{path}?v={version}"


def model_url(file: str, version: str) -> str:
    return f"/models3d/{file}?v={version}"


def product_json(p: Product, rules: Rules, version: str) -> dict:
    return {
        "sku": p.sku, "name": p.name, "audience": p.audience, "material": p.material,
        "frame_shape": p.frame_shape, "frame_label": rules.frame_shapes.get(p.frame_shape, {}).get("label", p.frame_shape.title()),
        "color": {"name": p.color_name, "hex": p.color_hex},
        "lens": {"name": p.lens_name, "hex": p.lens_hex},
        "size": p.size,
        "aspect": p.aspect, "scale": p.scale, "anchor": {"x": p.anchor_x, "y": p.anchor_y},
        "cutout": media(p.cutout, version), "thumb": media(p.thumb, version),
        "model": model_url(p.model, version),
    }


def match_json(m: Match, rules: Rules, version: str) -> dict:
    return {
        **product_json(m.product, rules, version),
        "match": {"percent": m.percent, "label": m.label, "top_pick": m.top_pick},
        "breakdown": {"shape": round(m.shape_score * 100), "proportion": round(m.proportion_score * 100) if m.proportion_label else None,
                      "fit": m.proportion_label},
        "reasons": m.reasons,
    }


def recommendations_json(rules: Rules, catalog: Catalog, profile: FaceProfile, matches: list[Match],
                         audience: str, all_matches: list[Match]) -> dict:
    return {
        "face_shape": profile.primary, "overridden": profile.overridden, "audience": audience,
        "styles": summarise_styles(rules, all_matches),
        "total": len(matches),
        "items": [match_json(m, rules, catalog.version) for m in matches],
    }


def face_json(a: FaceAnalysis, rules: Rules) -> dict:
    spec = rules.face_shapes[a.shape]
    best = sorted(spec["frames"].items(), key=lambda kv: -kv[1])
    return {
        "shape": a.shape, "label": spec["label"], "summary": spec["summary"], "principle": spec["principle"],
        "confidence": a.confidence, "needs_confirmation": a.needs_confirmation,
        "probabilities": [{"shape": s, "label": rules.face_shapes[s]["label"], "p": p} for s, p in a.probabilities.items()],
        "traits": explain.describe_face(a.measurements),
        "measurements": a.measurements,
        "guide_points": {k: list(v) for k, v in a.guide_points.items()},
        "face_box": list(a.face_box) if a.face_box else None,
        "best_frames": [rules.frame_shapes[f]["label"] for f, sc in best if sc >= 0.85 and f in rules.frame_shapes],
    }


def face_shapes_json(rules: Rules, in_stock: set[str]) -> list[dict]:
    out = []
    for key, spec in rules.face_shapes.items():
        ranked = sorted(spec["frames"].items(), key=lambda kv: -kv[1])
        out.append({"key": key, "label": spec["label"], "summary": spec["summary"], "principle": spec["principle"],
                    "best": [{"shape": f, "label": rules.frame_shapes[f]["label"]} for f, sc in ranked if sc >= 0.85 and f in in_stock],
                    "avoid": [{"shape": f, "label": rules.frame_shapes[f]["label"]} for f, sc in ranked[::-1] if sc <= 0.4 and f in in_stock][:2]})
    return out
