import pytest

from tryon.recommend import explain
from tryon.recommend.engine import FaceProfile, make_profile, proportion_fit, recommend, summarise_styles
from tryon.vision.face_shape import SHAPES

M = {"length_cheek": 1.2, "jaw_cheek": 0.8, "fore_jaw": 1.0, "chin_angle": 105}


def test_rules_cover_every_face_and_frame_shape(rules):
    assert set(rules.face_shapes) == set(SHAPES)
    for face, spec in rules.face_shapes.items():
        assert set(spec["frames"]) == set(rules.frame_shapes), face
        assert set(rules.raw["pairings"][face]) == set(rules.frame_shapes), face


def test_catalog_frames_are_all_known_to_the_rules(catalog, rules):
    assert catalog.products, "catalog is empty - run `tryon build`"
    assert {p.frame_shape for p in catalog.products} <= set(rules.frame_shapes)


def test_results_are_sorted_best_first_and_percentages_sane(catalog, rules):
    res = recommend(rules, catalog.products, make_profile("round", measurements=M, overridden=True))
    pcts = [m.percent for m in res]
    assert pcts == sorted(pcts, reverse=True)
    assert all(35 <= p <= 98 for p in pcts)
    assert sum(m.top_pick for m in res) == 6


def test_round_faces_prefer_angular_frames_over_round_ones(catalog, rules):
    res = recommend(rules, catalog.products, make_profile("round", overridden=True))
    best = {m.product.frame_shape for m in res[:10]}
    assert best <= {"rectangle", "square", "wayfarer", "geometric"}
    worst = res[-1].product.frame_shape
    assert worst in {"round", "oval"}


def test_override_ignores_probabilities(catalog, rules):
    probs = {"oval": 0.9, "round": 0.1}
    p = make_profile("square", probs, M, overridden=True)
    assert p.probabilities["square"] == 1.0 and p.primary == "square"
    blended = make_profile("oval", probs, M)
    assert blended.primary == "oval" and abs(sum(blended.probabilities.values()) - 1) < 1e-9


def test_blended_probabilities_average_the_scores(rules, catalog):
    product = next(p for p in catalog.products if p.frame_shape == "wayfarer")
    from tryon.recommend.engine import score_product
    pure_oval = score_product(rules, make_profile("oval", overridden=True), product).shape_score
    pure_heart = score_product(rules, make_profile("heart", overridden=True), product).shape_score
    mix = score_product(rules, FaceProfile({"oval": 0.5, "heart": 0.5, "round": 0, "square": 0, "oblong": 0}), product).shape_score
    assert mix == pytest.approx((pure_oval + pure_heart) / 2)


def test_kids_frames_stay_out_of_adult_results(catalog, rules):
    profile = make_profile("oval", overridden=True)
    assert all(m.product.audience != "kids" for m in recommend(rules, catalog.products, profile, audience="all"))
    assert all(m.product.audience == "kids" for m in recommend(rules, catalog.products, profile, audience="kids"))
    women = recommend(rules, catalog.products, profile, audience="women")
    assert women and all(m.product.audience in ("women", "unisex") for m in women)


def test_filters_and_style_summary(catalog, rules):
    profile = make_profile("oval", overridden=True)
    only = recommend(rules, catalog.products, profile, frame_shapes={"cat-eye"})
    assert only and {m.product.frame_shape for m in only} == {"cat-eye"}
    styles = summarise_styles(rules, recommend(rules, catalog.products, profile))
    assert [s["best_percent"] for s in styles] == sorted((s["best_percent"] for s in styles), reverse=True)


def test_every_match_explains_itself(catalog, rules):
    res = recommend(rules, catalog.products, make_profile("heart", measurements=M, overridden=False, probabilities={"heart": 1}))
    for m in res[:20]:
        assert 1 <= len(m.reasons) <= 3 and all(r.strip() for r in m.reasons)
        assert m.label


def test_proportion_fit_prefers_deeper_frames_for_longer_faces():
    deep, slim = 2.3, 3.4
    long_face = 1.38
    assert proportion_fit(deep, long_face)[0] > proportion_fit(slim, long_face)[0]
    assert proportion_fit(slim, 1.05)[0] > proportion_fit(deep, 1.05)[0]
    assert proportion_fit(2.9, None) == (0.8, None)


def test_describe_face_gauges_are_within_range():
    for t in explain.describe_face({"length_cheek": 9, "jaw_cheek": 0.1, "fore_jaw": 1.1, "chin_angle": 100}):
        assert 0 <= t["position"] <= 1 and t["note"] and t["value"]
