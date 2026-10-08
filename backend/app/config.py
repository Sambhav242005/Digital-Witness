from dataclasses import dataclass, field
from pathlib import Path
import os


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "backend/data")))
    public_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"))
    frontend_origin: str = field(default_factory=lambda: os.getenv("FRONTEND_ORIGIN", "http://localhost:3000"))
    max_queued_jobs: int = field(default_factory=lambda: int(os.getenv("MAX_QUEUED_JOBS", "20")))
    max_upload_bytes: int = 500 * 1024 * 1024
    relevance_threshold: float | None = field(default_factory=lambda: float(os.environ["RELEVANCE_THRESHOLD"]) if "RELEVANCE_THRESHOLD" in os.environ else None)
    worker_enabled: bool = True
    verification_yes_threshold: float = field(default_factory=lambda: float(os.getenv("VERIFICATION_YES_THRESHOLD", "0.8")))
    verification_no_threshold: float = field(default_factory=lambda: float(os.getenv("VERIFICATION_NO_THRESHOLD", "0.2")))

    def __post_init__(self):
        if not self.public_base_url.startswith(("http://", "https://")):
            raise ValueError("PUBLIC_BASE_URL must be an absolute HTTP(S) URL")
        if self.max_queued_jobs < 1:
            raise ValueError("MAX_QUEUED_JOBS must be positive")
        if self.relevance_threshold is not None and not -1 <= self.relevance_threshold <= 1:
            raise ValueError("RELEVANCE_THRESHOLD must be a finite cosine score in [-1,1]")
        if not 0 <= self.verification_no_threshold < self.verification_yes_threshold <= 1:
            raise ValueError("Verification thresholds must satisfy 0 <= no < yes <= 1")
