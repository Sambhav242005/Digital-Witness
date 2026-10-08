"""Google Gemini Embedding 2: bounded visual inputs, no local model fallback."""
import importlib.metadata
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from threading import RLock

from . import ModelUnavailable
from .vectors import normalize

MODEL_ID = "gemini-embedding-2"
MAX_INLINE_BYTES = 14 * 1024 * 1024  # Leaves room for base64 under 20 MB.


class GeminiEmbeddingAdapter:
    def __init__(self, api_key=None, model=MODEL_ID, timeout_ms=60000):
        self._api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY")
        self.revision = model
        self.timeout_ms = timeout_ms
        self.available = False
        self.error = "Gemini embedding model loading has not been requested"
        self._client = None
        self._lock = RLock()

    @property
    def fingerprint(self):
        try:
            version = importlib.metadata.version("google-genai")
        except importlib.metadata.PackageNotFoundError:
            version = "missing"
        return f"google-gemini-api@{self.revision}|768|normalized|video-only|trim-before-1fps-round-up|640px|x264-crf28-v1|google-genai={version}"

    def _request(self, contents):
        from google.genai import types
        try:
            response = self._client.models.embed_content(
                model=self.revision, contents=contents,
                config=types.EmbedContentConfig(output_dimensionality=768),
            )
            if not response.embeddings or len(response.embeddings) != 1:
                raise ValueError("Expected exactly one aggregated embedding")
            return normalize(response.embeddings[0].values)
        except Exception:
            # SDK errors can contain request details. Never retain or chain them.
            raise ModelUnavailable("Gemini embedding request failed; check credentials, quota, model access, and network") from None

    def load(self):
        with self._lock:
            self.available = False
            self.close()
            if not self._api_key:
                self.error = "GEMINI_API_KEY is required for Gemini embeddings"
                raise ModelUnavailable(self.error)
            try:
                from google import genai
                from google.genai import types
                self._client = genai.Client(
                    api_key=self._api_key,
                    http_options=types.HttpOptions(
                        timeout=self.timeout_ms,
                        retry_options=types.HttpRetryOptions(attempts=2, initial_delay=1, max_delay=2),
                    ),
                )
                for query in ("a person carrying a bag", "an empty outdoor scene"):
                    self._request(f"task: search result | query: {query}")
                with tempfile.TemporaryDirectory(prefix="dw-gemini-smoke-") as directory:
                    clip = Path(directory) / "smoke.mp4"
                    subprocess.run([
                        "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi",
                        "-i", "testsrc2=size=128x128:rate=1", "-t", "1", "-an",
                        "-c:v", "libx264", "-threads", "1", str(clip),
                    ], check=True, capture_output=True, timeout=30)
                    self._request([types.Part.from_bytes(data=clip.read_bytes(), mime_type="video/mp4")])
                self.available = True
                self.error = None
            except Exception:
                self.close()
                self.error = "Gemini embedding smoke test failed; check credentials, quota, model access, FFmpeg, and network"
                raise ModelUnavailable(self.error) from None

    def close(self):
        with self._lock:
            self.available = False
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None

    def embed_text(self, query):
        with self._lock:
            if not self.available or self._client is None:
                raise ModelUnavailable(self.error or "Gemini embedding model unavailable")
            return self._request(f"task: search result | query: {query}")

    def embed_clip(self, video_path, start_sec, end_sec):
        if not all(math.isfinite(x) for x in (start_sec, end_sec)) or not 0 <= start_sec < end_sec or end_sec-start_sec > 8:
            raise ValueError("Clip must be a finite interval no longer than eight seconds")
        with self._lock:
            if not self.available or self._client is None:
                raise ModelUnavailable(self.error or "Gemini embedding model unavailable")
            from google.genai import types
            with tempfile.TemporaryDirectory(prefix="dw-gemini-embedding-") as directory:
                clip = Path(directory) / "clip.mp4"
                try:
                    subprocess.run([
                        "ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", str(start_sec),
                        "-i", str(video_path), "-t", str(end_sec-start_sec), "-an",
                        "-vf", f"trim=duration={end_sec-start_sec},setpts=PTS-STARTPTS,fps=1:round=up,scale=640:640:force_original_aspect_ratio=decrease:force_divisible_by=2",
                        "-c:v", "libx264", "-crf", "28", "-preset", "ultrafast", "-threads", "1", str(clip),
                    ], check=True, capture_output=True, timeout=120)
                    if not 0 < clip.stat().st_size <= MAX_INLINE_BYTES:
                        raise ValueError("Bounded inline video exceeds request budget")
                    probe = subprocess.run([
                        "ffprobe", "-v", "error", "-count_frames", "-show_entries",
                        "stream=nb_read_frames", "-of", "json", str(clip),
                    ], check=True, capture_output=True, timeout=30)
                    streams = json.loads(probe.stdout).get("streams", [])
                    if not streams or not any(int(stream.get("nb_read_frames", 0)) > 0 for stream in streams):
                        raise ValueError("Clip interval contains no decodable source frames")
                    return self._request([types.Part.from_bytes(data=clip.read_bytes(), mime_type="video/mp4")])
                except ModelUnavailable:
                    raise
                except Exception:
                    raise ModelUnavailable("Video could not be prepared within Gemini inline upload limits") from None
