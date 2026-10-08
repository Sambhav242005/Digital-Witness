import json
from types import SimpleNamespace

import pytest
from google import genai
from google.genai import types
from PIL import Image

from app.ai import ModelUnavailable
from app.ai.gemini_verification import GeminiVerificationAdapter, VisualDecision
from app.ai.verification_adapter import CHECKS


def fake_client(monkeypatch, answer="yes", failure=False):
    calls, closed = [], []
    def generate_content(**kwargs):
        calls.append(kwargs)
        config = kwargs["config"]
        assert isinstance(config, types.GenerateContentConfig)
        assert isinstance(config.response_schema, types.Schema)
        assert config.response_schema.properties["answer"].enum == ["yes", "no", "uncertain"]
        assert config.response_schema.additional_properties is None
        assert config.response_mime_type == "application/json"
        assert config.thinking_config.thinking_level == types.ThinkingLevel.LOW
        assert config.max_output_tokens == 1024
        part = kwargs["contents"][0]
        assert isinstance(part, types.Part)
        assert part.inline_data.mime_type in {"image/png", "image/jpeg"}
        assert part.inline_data.data
        if failure:
            raise RuntimeError("SECRET_KEY included in provider failure")
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=[types.Part(text=json.dumps({"answer": answer}))]))])
    def client(**kwargs):
        assert kwargs["api_key"] == "SECRET_KEY"
        assert kwargs["http_options"].timeout == 60000
        assert kwargs["http_options"].retry_options.attempts == 1
        return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content), close=lambda: closed.append(True))
    monkeypatch.setattr(genai, "Client", client)
    return calls, closed


def readable_image(path):
    image = Image.new("L", (128, 128))
    image.putdata([255 if (x//8+y//8) % 2 else 0 for y in range(128) for x in range(128)])
    image.save(path)


@pytest.mark.parametrize("answer", ["yes", "no", "uncertain"])
def test_structured_frame_decision_without_probability(monkeypatch, tmp_path, answer):
    calls, closed = fake_client(monkeypatch, answer)
    adapter = GeminiVerificationAdapter(api_key="SECRET_KEY")
    assert not adapter.available
    adapter.load()
    assert adapter.available and len(calls) == 1
    path = tmp_path / "frame.png"
    readable_image(path)
    assert adapter.check(path, "bag_present", CHECKS["bag_present"]) == {"answer": answer, "probability_yes": None}
    assert len(calls) == 2
    assert "SECRET_KEY" not in adapter.fingerprint
    adapter.close()
    assert closed and not adapter.available


def test_poor_and_unknown_checks_make_no_call(monkeypatch, tmp_path):
    calls, _ = fake_client(monkeypatch)
    adapter = GeminiVerificationAdapter(api_key="SECRET_KEY")
    adapter.load()
    path = tmp_path / "blank.png"
    Image.new("RGB", (128, 128), "gray").save(path)
    assert adapter.check(path, "bag_present", CHECKS["bag_present"]) == {"answer": "uncertain", "probability_yes": None}
    assert adapter.check(tmp_path / "missing.png", "bag_present", CHECKS["bag_present"])["answer"] == "uncertain"
    with pytest.raises(ValueError):
        adapter.check(path, "identity", "Who is this?")
    with pytest.raises(ValueError):
        adapter.check(path, "bag_present", "Has the bag been abandoned?")
    assert len(calls) == 1


@pytest.mark.parametrize("answer,failure", [("unknown", False), ("yes", True)])
def test_failed_smoke_remains_unavailable_and_sanitized(monkeypatch, answer, failure):
    _, closed = fake_client(monkeypatch, answer, failure)
    adapter = GeminiVerificationAdapter(api_key="SECRET_KEY")
    with pytest.raises(ModelUnavailable) as caught:
        adapter.load()
    assert not adapter.available and closed and adapter._client is None
    assert "SECRET_KEY" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_missing_key_and_unloaded_no_network(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(genai, "Client", lambda **kwargs: pytest.fail("No credentials should make no client"))
    adapter = GeminiVerificationAdapter()
    with pytest.raises(ModelUnavailable):
        adapter.load()
    with pytest.raises(ModelUnavailable):
        adapter.check("image.png", "bag_present", CHECKS["bag_present"])


def test_environment_model(monkeypatch):
    monkeypatch.setenv("GEMINI_VERIFICATION_MODEL", "gemini-test")
    assert GeminiVerificationAdapter().revision == "gemini-test"
