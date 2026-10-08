import math

import pytest
from PIL import Image

from app.ai import ModelUnavailable
from app.ai.vectors import normalize
from app.ai.gemini_verification import GeminiVerificationAdapter
from app.ai.verification_adapter import (
    CHECKS, aggregate_checks, answer_for_probability,
    checks_for_query, image_quality,
)


@pytest.mark.parametrize("vector", [[0.] * 768, [math.nan] * 768, [math.inf] * 768, [1.] * 767, [1e308] * 768])
def test_invalid_embedding_rejected(vector):
    with pytest.raises(ValueError):
        normalize(vector)


def test_normalization():
    vector = normalize([2.] * 768)
    assert len(vector) == 768
    assert sum(x*x for x in vector) == pytest.approx(1.)


@pytest.mark.parametrize("query", [
    "no bag", "person without a bag", "not carrying a bag", "unattended bag",
    "a person abandoned their bag", "bag owner", "person entered with bag", "red car",
    "same person carrying a bag", "bag left behind", "person leaving their bag",
])
def test_unsupported_semantics_are_not_frame_verified(query):
    assert checks_for_query(query) == []


def test_allowlist():
    assert checks_for_query("Person carrying a backpack") == [
        {"check_id": "person_carrying_bag", "question": CHECKS["person_carrying_bag"]},
    ]
    assert checks_for_query("a bag on the floor")[0]["check_id"] == "bag_present"


@pytest.mark.parametrize("probability,answer", [(0., "no"), (.2, "no"), (.5, "uncertain"), (.8, "yes"), (1., "yes"), (None, "uncertain")])
def test_probability_thresholds(probability, answer):
    assert answer_for_probability(probability) == answer


@pytest.mark.parametrize("probability", [math.nan, math.inf, -.1, 1.1])
def test_invalid_probability(probability):
    with pytest.raises(ValueError):
        answer_for_probability(probability)


def test_invalid_thresholds():
    with pytest.raises(ValueError):
        answer_for_probability(.8, yes_threshold=.2, no_threshold=.8)


@pytest.mark.parametrize("answers,status", [(["yes"], "supported"), (["no"], "contradicted"), (["yes", "no"], "uncertain"), (["yes", "uncertain"], "uncertain"), ([], "uncertain")])
def test_aggregation(answers, status):
    frames = [{"quality": "usable", "checks": [{"answer": x} for x in answers]}]
    assert aggregate_checks(frames)["status"] == status
    # Poor-frame confidence never changes the conclusion.
    frames.append({"quality": "poor", "checks": [{"answer": "yes"}]})
    assert aggregate_checks(frames)["status"] == status


def test_quality(tmp_path):
    blank = tmp_path / "blank.png"
    Image.new("RGB", (128, 128), "gray").save(blank)
    assert image_quality(blank) == "poor"
    tiny = tmp_path / "tiny.png"
    Image.new("RGB", (32, 32), "white").save(tiny)
    assert image_quality(tiny) == "poor"
    assert image_quality(tmp_path / "missing.png") == "poor"
    readable = tmp_path / "texture.png"
    image = Image.new("L", (128, 128))
    image.putdata([255 if (x//8 + y//8) % 2 else 0 for y in range(128) for x in range(128)])
    image.save(readable)
    assert image_quality(readable) == "usable"


def test_unavailable_verification(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    verification = GeminiVerificationAdapter()
    with pytest.raises(ModelUnavailable):
        verification.load()
    with pytest.raises(ModelUnavailable):
        verification.check("frame.png", "bag_present", CHECKS["bag_present"])
    with pytest.raises(ValueError):
        verification.check("frame.png", "identity", "Who is this?")
    assert not verification.available
