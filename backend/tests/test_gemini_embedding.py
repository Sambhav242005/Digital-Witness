import math
import subprocess
import tempfile
import json
from types import SimpleNamespace

import pytest
from google import genai
from google.genai import types

from app.ai import ModelUnavailable
from app.ai.gemini_embedding import GeminiEmbeddingAdapter


def sdk_client(monkeypatch, invalid_video=False, failure=False):
    calls = []
    closed = []
    def embed_content(**kwargs):
        calls.append(kwargs)
        assert isinstance(kwargs["config"], types.EmbedContentConfig)
        assert kwargs["config"].output_dimensionality == 768
        assert kwargs["config"].task_type is None
        if failure:
            raise RuntimeError("server error includes SECRET_KEY")
        video = isinstance(kwargs["contents"], list)
        if video:
            part = kwargs["contents"][0]
            assert isinstance(part, types.Part)
            assert part.inline_data.mime_type == "video/mp4"
            assert len(part.inline_data.data) > 100
            with tempfile.NamedTemporaryFile(suffix=".mp4") as video_file:
                video_file.write(part.inline_data.data)
                video_file.flush()
                probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries", "stream=nb_read_frames", "-of", "json", video_file.name], check=True, capture_output=True)
                streams = json.loads(probe.stdout)["streams"]
                assert streams and int(streams[0]["nb_read_frames"]) > 0
        return types.EmbedContentResponse(embeddings=[types.ContentEmbedding(
            values=[math.nan if video and invalid_video else 1.] * 768,
        )])
    def client(**kwargs):
        assert kwargs["api_key"] == "SECRET_KEY"
        assert kwargs["http_options"].timeout == 60000
        assert kwargs["http_options"].retry_options.attempts == 1
        return SimpleNamespace(models=SimpleNamespace(embed_content=embed_content), close=lambda: closed.append(True))
    monkeypatch.setattr(genai, "Client", client)
    return calls, closed


def test_missing_key_no_network(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(genai, "Client", lambda **kw: pytest.fail("No credential should create no client"))
    adapter = GeminiEmbeddingAdapter()
    with pytest.raises(ModelUnavailable, match="GEMINI_API_KEY"):
        adapter.load()
    assert not adapter.available
    with pytest.raises(ModelUnavailable):
        adapter.embed_text("bag")


def test_load_and_bounded_video_request(monkeypatch, tmp_path):
    calls, closed = sdk_client(monkeypatch)
    adapter = GeminiEmbeddingAdapter(api_key="SECRET_KEY")
    assert not adapter.available
    adapter.load()
    assert adapter.available and len(calls) == 3
    assert all(call["contents"].startswith("task: search result | query:") for call in calls[:2])
    assert calls[0]["contents"] != calls[1]["contents"]
    assert isinstance(calls[2]["contents"][0], types.Part)
    result = adapter.embed_text("person carrying a bag")
    assert len(result) == 768 and sum(x*x for x in result) == pytest.approx(1.)
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=800x600:rate=25",
        "-t", "2", "-c:v", "libx264", "-threads", "1", str(source),
    ], check=True, capture_output=True)
    assert len(adapter.embed_clip(source, .5, 1.5)) == 768
    # Final partial windows also contain a decodable frame.
    assert len(adapter.embed_clip(source, 1.9, 2.)) == 768
    assert "google-genai=2.29.0" in adapter.fingerprint
    assert "SECRET_KEY" not in adapter.fingerprint
    adapter.close()
    assert closed and not adapter.available


@pytest.mark.parametrize("invalid_video,failure", [(True, False), (False, True)])
def test_smoke_failure_closes_and_redacts(monkeypatch, invalid_video, failure):
    calls, closed = sdk_client(monkeypatch, invalid_video, failure)
    adapter = GeminiEmbeddingAdapter(api_key="SECRET_KEY")
    with pytest.raises(ModelUnavailable) as caught:
        adapter.load()
    assert not adapter.available and adapter._client is None and closed
    assert "SECRET_KEY" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


@pytest.mark.parametrize("start,end", [(0., 9.), (-1., 1.), (1., 1.), (math.nan, 2.), (0., math.inf)])
def test_invalid_interval_no_network(start, end):
    with pytest.raises(ValueError):
        GeminiEmbeddingAdapter(api_key="SECRET_KEY").embed_clip("unused.mp4", start, end)
