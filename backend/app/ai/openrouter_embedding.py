"""Image-and-text embeddings through OpenRouter's OpenAI-compatible API."""
import base64
import importlib.metadata
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from threading import RLock

from openai import OpenAI

from . import ModelUnavailable
from .upstream import ProviderCooldown
from .vectors import normalize

MODEL_ID = "nvidia/llama-nemotron-embed-vl-1b-v2:free"


class OpenRouterEmbeddingAdapter(ProviderCooldown):
    provider_name = "OpenRouter"
    def __init__(self, api_key=None, model=None, base_url=None, client=None):
        self.api_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("OPENROUTER_EMBEDDING_MODEL", MODEL_ID)
        self.base_url = (base_url or os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")).rstrip("/")
        self.client = client
        self.dimension = None
        self.revision = self.model
        self.error = "OpenRouter embedding model has not been loaded"
        self._lock = RLock()

    @property
    def fingerprint(self):
        try:
            version = importlib.metadata.version("openai")
        except importlib.metadata.PackageNotFoundError:
            version = "missing"
        return f"openrouter@{self.model}|{self.dimension or 'unloaded'}|normalized|sampled-jpeg-1fps-max640-v1|openai={version}"

    def _request(self, inputs):
        try:
            response = self.client.embeddings.create(model=self.model, input=inputs, encoding_format="float")
            vectors = [normalize(item.embedding, dimension=None) for item in response.data]
            if len(vectors) != (len(inputs) if isinstance(inputs, list) else 1):
                raise ValueError("Embedding response count does not match inputs")
            dimensions = {len(v) for v in vectors}
            if len(dimensions) != 1 or (self.dimension and dimensions != {self.dimension}):
                raise ValueError("Embedding dimension changed")
            self.dimension = len(vectors[0])
            return vectors
        except Exception as exc:
            raise self.provider_failure(exc, "OpenRouter embedding") from None

    def load(self):
        with self._lock:
            self.available = False
            if not self.api_key:
                self.error = "OPENROUTER_API_KEY is required for OpenRouter embeddings"
                raise ModelUnavailable(self.error)
            try:
                self.client = self.client or OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=60, max_retries=0)
                self._request("Digital Witness image retrieval smoke test")
                with tempfile.TemporaryDirectory(prefix="dw-openrouter-smoke-") as directory:
                    path = Path(directory) / "smoke.png"
                    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc2=size=128x128:rate=1", "-frames:v", "1", str(path)], check=True, capture_output=True, timeout=30)
                    data = base64.b64encode(path.read_bytes()).decode("ascii")
                    self._request([{"content": [{"type": "text", "text": "A sampled frame from a video recording"}, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}]}])
                self.available = True
                self.error = None
            except ModelUnavailable as exc:
                if exc.details.get("retry_after_sec"):
                    self._needs_reload = True
                else:
                    self.close()
                self.error = str(exc)
                raise
            except Exception as exc:
                self.close()
                self.error = f"OpenRouter embedding smoke test failed ({type(exc).__name__}); check model access, quota, and network"
                raise ModelUnavailable(self.error) from None

    def embed_text(self, query):
        with self._lock:
            if not self.available:
                raise self.unavailable(self.error or "OpenRouter embedding model unavailable")
            return self._request(query)[0]

    def embed_clip(self, video_path, start_sec, end_sec):
        if not all(math.isfinite(x) for x in (start_sec, end_sec)) or not 0 <= start_sec < end_sec or end_sec-start_sec > 8:
            raise ValueError("Clip must be a finite interval no longer than eight seconds")
        with self._lock, tempfile.TemporaryDirectory(prefix="dw-openrouter-frames-") as directory:
            if not self.available:
                raise self.unavailable(self.error or "OpenRouter embedding model unavailable")
            pattern = Path(directory) / "frame-%02d.jpg"
            try:
                subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", str(start_sec), "-i", str(video_path), "-t", str(end_sec-start_sec), "-an", "-vf", "fps=1:round=up,scale=640:640:force_original_aspect_ratio=decrease", "-q:v", "6", str(pattern)], check=True, capture_output=True, timeout=120)
                paths = sorted(Path(directory).glob("frame-*.jpg"))
                if not paths or len(paths) > 8:
                    raise ValueError("No bounded sample frames")
                content = [{"type": "text", "text": "Video clip with source interval %.2f to %.2f seconds; sampled frames in chronological order." % (start_sec, end_sec)}]
                for path in paths:
                    data = base64.b64encode(path.read_bytes()).decode("ascii")
                    content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}})
                vectors = self._request([{"content": content}])
                return normalize(vectors[0], self.dimension)
            except ModelUnavailable:
                raise
            except Exception as exc:
                raise ModelUnavailable(f"Could not prepare clip frames for OpenRouter ({type(exc).__name__})") from None

    def close(self):
        self.available = False
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
