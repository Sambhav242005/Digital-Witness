import base64
from types import SimpleNamespace

import pytest

from app.ai import ModelUnavailable
from app.ai.openrouter_embedding import OpenRouterEmbeddingAdapter


class Embeddings:
    def __init__(self, dim=4):
        self.requests = []
        self.dim = dim

    def create(self, **kwargs):
        self.requests.append(kwargs)
        count = len(kwargs['input']) if isinstance(kwargs['input'], list) else 1
        return SimpleNamespace(data=[SimpleNamespace(embedding=[1.0] * self.dim) for _ in range(count)])


class FakeClient:
    def __init__(self):
        self.embeddings = Embeddings()
        self.closed = False

    def close(self): self.closed = True


def test_openrouter_embedding_normalizes_dynamic_dimensions_and_checks_image_input():
    client = FakeClient()
    adapter = OpenRouterEmbeddingAdapter(api_key='secret', client=client)
    adapter.dimension = 4
    adapter.available = True
    vector = adapter.embed_text('parcel beside door')
    assert len(vector) == 4
    assert sum(x*x for x in vector) == pytest.approx(1.)
    assert client.embeddings.requests[-1]['model'] == 'nvidia/llama-nemotron-embed-vl-1b-v2:free'


def test_missing_openrouter_key_does_not_make_a_request(monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    adapter = OpenRouterEmbeddingAdapter()
    with pytest.raises(ModelUnavailable, match='OPENROUTER_API_KEY'):
        adapter.load()


def test_clip_samples_chronological_images(tmp_path):
    client = FakeClient()
    adapter = OpenRouterEmbeddingAdapter(api_key='secret', client=client)
    adapter.dimension = 4
    adapter.available = True
    source = tmp_path / 'clip.mp4'
    import subprocess
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=128x128:rate=2','-t','3','-c:v','libx264','-threads','1','-y',str(source)],check=True,capture_output=True)
    vector = adapter.embed_clip(source, 0, 3)
    payload = client.embeddings.requests[-1]['input'][0]['content']
    images = [part for part in payload if part['type'] == 'image_url']
    assert 1 <= len(images) <= 3
    assert all(part['image_url']['url'].startswith('data:image/jpeg;base64,') for part in images)
    assert all(base64.b64decode(part['image_url']['url'].split(',',1)[1]) for part in images)
    assert len(vector) == 4
