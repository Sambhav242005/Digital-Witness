import math
import subprocess
from pathlib import Path

import pytest

from app.ai import ModelUnavailable
from app.ai.huggingface_embedding import MODEL_ID, MODEL_REVISION, HuggingFaceEmbeddingAdapter


class FakeModel:
    def __init__(self):
        self.calls = []

    def encode(self, value, **kwargs):
        self.calls.append((value, kwargs))
        if isinstance(value, dict):
            for path in value["image"]:
                if isinstance(path, str):
                    assert Path(path).is_file()
        return [1.0] * 768


def fake_ffmpeg(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        pattern = args[-1]
        for index in (1, 2):
            Path(pattern.replace("%02d", f"{index:02d}")).write_bytes(b"jpeg-frame")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("app.ai.huggingface_embedding.subprocess.run", run)
    return calls


def test_load_checks_hugging_face_text_and_image_embeddings():
    model = FakeModel()
    adapter = HuggingFaceEmbeddingAdapter(model=model)

    adapter.load()

    assert adapter.available
    assert adapter.model_id == MODEL_ID
    assert adapter.revision == MODEL_REVISION
    assert adapter.dimension == 768
    assert model.calls[0][0] == "Digital Witness embedding smoke test"
    assert model.calls[0][1]["prompt_name"] == "SearchQuery"
    image_input = model.calls[1][0]
    assert image_input["text"] == "Video frame. <|image|>"
    assert image_input["image"][0].size == (32, 32)
    assert adapter.embed_text("person carrying a bag") == pytest.approx([1 / math.sqrt(768)] * 768)
    assert model.calls[-1][1]["prompt_name"] == "SearchQuery"
    adapter.close()


def test_clip_combines_ordered_image_frames_in_one_embedding(monkeypatch):
    ffmpeg_calls = fake_ffmpeg(monkeypatch)
    model = FakeModel()
    adapter = HuggingFaceEmbeddingAdapter(model=model)
    adapter._available = True
    adapter.dimension = 768

    vector = adapter.embed_clip("source.mp4", 4.5, 6.5)

    assert vector == pytest.approx([1 / math.sqrt(768)] * 768)
    args = ffmpeg_calls[0]
    assert args[args.index("-ss") + 1] == "4.5"
    assert args[args.index("-t") + 1] == "2.0"
    clip_input = model.calls[0][0]
    assert clip_input["text"] == "Video recording sampled at 4.50s, 5.50s. <|image|> <|image|>"
    assert len(clip_input["image"]) == 2
    assert model.calls[0][1]["prompt_name"] is None


@pytest.mark.parametrize("start,end", [(0.0, 9.0), (-1.0, 1.0), (1.0, 1.0), (math.nan, 2.0), (0.0, math.inf)])
def test_invalid_clip_interval_is_rejected(start, end):
    with pytest.raises(ValueError):
        HuggingFaceEmbeddingAdapter().embed_clip("unused.mp4", start, end)


def test_embedding_model_download_option_defaults_on():
    assert HuggingFaceEmbeddingAdapter(model=FakeModel()).auto_download
    assert not HuggingFaceEmbeddingAdapter(model=FakeModel(), auto_download=False).auto_download


def test_failed_model_smoke_does_not_advertise_embeddings():
    class InvalidModel:
        def encode(self, value, **kwargs):
            return [1.0] * 512

    adapter = HuggingFaceEmbeddingAdapter(model=InvalidModel())

    with pytest.raises(ModelUnavailable, match="smoke test failed"):
        adapter.load()

    assert not adapter.available
