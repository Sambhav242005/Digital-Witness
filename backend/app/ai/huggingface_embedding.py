"""Local multimodal EmbeddingGemma 2 inference through Hugging Face."""
import importlib.metadata
import math
import os
import subprocess
import tempfile
from pathlib import Path
from threading import RLock

from . import ModelUnavailable
from .vectors import normalize

MODEL_ID = "google/embeddinggemma-2"
MODEL_REVISION = "914f7f89142e33e77833254d9c9b90c3cef7303b"
VECTOR_DIMENSION = 768


class HuggingFaceEmbeddingAdapter:
    provider_name = "Hugging Face EmbeddingGemma 2"

    def __init__(self, model_id=None, revision=None, auto_download=None, model=None):
        self.model_id = model_id or os.getenv("HF_EMBEDDING_MODEL", MODEL_ID)
        self.revision = revision or os.getenv("HF_EMBEDDING_REVISION", MODEL_REVISION)
        if auto_download is None:
            auto_download = os.getenv("HF_AUTO_DOWNLOAD_EMBEDDING", "true").lower() == "true"
        self.auto_download = auto_download
        self.model = model
        self.dimension = None
        self.error = "Hugging Face embedding model has not been loaded"
        self._available = False
        self._lock = RLock()

    @property
    def available(self):
        return self._available

    @property
    def fingerprint(self):
        versions = []
        for package in ("sentence-transformers", "transformers", "torch"):
            try:
                version = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                version = "missing"
            versions.append(f"{package}={version}")
        return f"huggingface@{self.model_id}@{self.revision}|{self.dimension or VECTOR_DIMENSION}|normalized|image-1fps-max640-v1|{'|'.join(versions)}"

    def _new_model(self):
        import torch
        from sentence_transformers import SentenceTransformer

        dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float32
        return SentenceTransformer(
            self.model_id,
            revision=self.revision,
            device="cuda" if torch.cuda.is_available() else "cpu",
            model_kwargs={"torch_dtype": dtype},
            config_kwargs={"audio_config": None},
            local_files_only=not self.auto_download,
        )

    def _encode(self, input_value, prompt_name=None):
        try:
            vector = self.model.encode(
                input_value,
                prompt_name=prompt_name,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
            return normalize(vector, self.dimension or VECTOR_DIMENSION)
        except ModelUnavailable:
            raise
        except Exception as exc:
            raise ModelUnavailable(f"Hugging Face embedding inference failed ({type(exc).__name__})") from None

    def load(self):
        with self._lock:
            self._available = False
            try:
                if self.model is None:
                    self.model = self._new_model()
                text_vector = self._encode("Digital Witness embedding smoke test", "SearchQuery")
                image_vector = self._encode({"text": "Video frame. <|image|>", "image": [self._smoke_image()]})
                if len(text_vector) != len(image_vector):
                    raise ValueError("Text and image embedding dimensions differ")
                self.dimension = len(text_vector)
                if self.dimension != VECTOR_DIMENSION:
                    raise ValueError("Unexpected EmbeddingGemma 2 output dimension")
                self._available = True
                self.error = None
            except Exception as exc:
                self.model = None
                self.error = f"Hugging Face embedding smoke test failed ({type(exc).__name__}); verify model access, memory, and network"
                raise ModelUnavailable(self.error) from None

    @staticmethod
    def _smoke_image():
        from PIL import Image

        image = Image.new("RGB", (32, 32), "white")
        return image

    def embed_text(self, query):
        with self._lock:
            if not self.available:
                raise ModelUnavailable(self.error or "Hugging Face embedding model unavailable")
            return self._encode(query, "SearchQuery")

    def embed_clip(self, video_path, start_sec, end_sec):
        if not all(math.isfinite(value) for value in (start_sec, end_sec)) or not 0 <= start_sec < end_sec or end_sec - start_sec > 8:
            raise ValueError("Clip must be a finite interval no longer than eight seconds")
        with self._lock, tempfile.TemporaryDirectory(prefix="dw-hf-embedding-frames-") as directory:
            if not self.available:
                raise ModelUnavailable(self.error or "Hugging Face embedding model unavailable")
            pattern = Path(directory) / "frame-%02d.jpg"
            try:
                subprocess.run([
                    "ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", str(start_sec),
                    "-i", str(video_path), "-t", str(end_sec - start_sec), "-an",
                    "-vf", "fps=1:round=up,scale=640:640:force_original_aspect_ratio=decrease",
                    "-q:v", "6", str(pattern),
                ], check=True, capture_output=True, timeout=120)
                paths = sorted(Path(directory).glob("frame-*.jpg"))
                if not paths or len(paths) > 8:
                    raise ValueError("No bounded sample frames")
                placeholders = " ".join("<|image|>" for _ in paths)
                times = ", ".join(f"{start_sec + index:.2f}s" for index in range(len(paths)))
                return self._encode({
                    "text": f"Video recording sampled at {times}. {placeholders}",
                    "image": [str(path) for path in paths],
                })
            except ModelUnavailable:
                raise
            except (subprocess.SubprocessError, OSError, ValueError) as exc:
                raise ModelUnavailable(f"Video clip could not be prepared for Hugging Face image embedding ({type(exc).__name__})") from None

    def close(self):
        with self._lock:
            self._available = False
            if self.model is not None:
                del self.model
                self.model = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
