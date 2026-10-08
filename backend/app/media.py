"""Local media processing. Callers resolve opaque media IDs before using this module."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import subprocess
from typing import Iterator

from starlette.responses import Response, StreamingResponse


class MediaError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _run(arguments: list[str], timeout: int = 7200) -> str:
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout, check=True)
        return result.stdout
    except FileNotFoundError:
        raise MediaError("MEDIA_DECODE_FAILED", "FFmpeg and ffprobe must be installed to process recordings.") from None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        raise MediaError("MEDIA_DECODE_FAILED", "The recording could not be decoded or processing timed out.") from None


def _probe(source: Path) -> dict:
    try:
        return json.loads(_run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source)], 60))
    except (ValueError, TypeError):
        raise MediaError("MEDIA_DECODE_FAILED", "The recording has invalid media metadata.") from None


def frame(source: Path, timestamp: float, destination: Path) -> Path:
    if not math.isfinite(timestamp) or timestamp < 0:
        raise MediaError("MEDIA_DECODE_FAILED", "The requested frame timestamp is invalid.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-y", "-ss", str(timestamp), "-i", str(source), "-map", "0:v:0", "-frames:v", "1", "-q:v", "2", str(destination)], 120)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise MediaError("MEDIA_DECODE_FAILED", "No readable frame exists at the requested timestamp.")
    return destination


def prepare(source: Path, output_dir: Path) -> dict:
    """Validate MP4 and publish a normalized browser derivative only after full decode."""
    metadata = _probe(source)
    container = metadata.get("format", {})
    # ffprobe's MOV demuxer also handles QuickTime; require an MP4-family brand.
    brand = container.get("tags", {}).get("major_brand", "").strip()
    if "mp4" not in container.get("format_name", "").split(",") or brand not in {"isom", "iso2", "iso3", "iso4", "iso5", "iso6", "iso7", "iso8", "iso9", "mp41", "mp42", "avc1", "dash", "M4V", "M4A", "MSNV"}:
        raise MediaError("MEDIA_DECODE_FAILED", "Upload a valid MP4 recording.")
    video = next((s for s in metadata.get("streams", []) if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise MediaError("MEDIA_DECODE_FAILED", "The MP4 contains no video stream.")
    try:
        duration = float(video.get("duration", container.get("duration", 0)))
        origin = float(container.get("start_time", 0))
        video_start = float(video.get("start_time", origin))
        recording_duration = max(0, video_start - origin) + duration
        width, height = int(video["width"]), int(video["height"])
        if not all(math.isfinite(v) for v in (duration, origin, video_start, recording_duration)) or duration <= 0 or width <= 0 or height <= 0:
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise MediaError("MEDIA_DECODE_FAILED", "The recording has invalid duration or dimensions.") from None
    if recording_duration > 1800:
        raise MediaError("DURATION_EXCEEDED", "Recordings must be 30 minutes or shorter.")
    output_dir.mkdir(parents=True, exist_ok=True)
    partial = output_dir / "playback.partial.mp4"
    playback = output_dir / "playback.mp4"
    thumbnail = output_dir / "thumbnail.jpg"
    try:
        # Normalize the container's start to recording-relative zero, retaining
        # variable frame timestamps and stream offsets rather than forcing FPS.
        _run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-y", "-copyts", "-start_at_zero", "-i", str(source), "-map", f"0:{video['index']}", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough", "-c:a", "aac", "-t", str(recording_duration), "-movflags", "+faststart", str(partial)])
        frame(partial, 0, thumbnail)
        prepared = _probe(partial)
        stream = next(s for s in prepared["streams"] if s["codec_type"] == "video")
        prepared_duration = float(prepared["format"]["duration"])
        if not math.isfinite(prepared_duration) or prepared_duration <= 0:
            raise MediaError("MEDIA_DECODE_FAILED", "The prepared recording has invalid duration.")
        partial.replace(playback)
        return {"duration_sec": prepared_duration, "width": int(stream["width"]), "height": int(stream["height"]), "playback_path": playback, "thumbnail_path": thumbnail}
    except Exception:
        partial.unlink(missing_ok=True)
        thumbnail.unlink(missing_ok=True)
        raise


def windows(duration: float, window: float = 8, stride: float = 4) -> list[tuple[float, float]]:
    if any(not math.isfinite(v) or v <= 0 for v in (duration, window, stride)):
        raise ValueError("Window parameters must be finite and positive")
    return [(i * stride, min(i * stride + window, duration)) for i in range(math.ceil(duration / stride))]


def media_response(path: Path, content_type: str, range_header: str | None = None) -> Response:
    """Serve an already ID-resolved path with a bounded single byte range."""
    if not path.is_file():
        raise MediaError("MEDIA_NOT_FOUND", "The requested media is unavailable.")
    size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(size)}
    start, end, status = 0, size - 1, 200
    if range_header:
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        try:
            if not match or not any(match.groups()) or size == 0:
                raise ValueError
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), size - 1) if last else size - 1
            else:
                suffix = int(last)
                if suffix <= 0:
                    raise ValueError
                start, end = max(0, size - suffix), size - 1
            if start >= size or start > end:
                raise ValueError
        except ValueError:
            return Response(status_code=416, headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes */{size}", "Content-Length": "0"})
        status = 206
        headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})

    def chunks() -> Iterator[bytes]:
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = max(0, end - start + 1)
            while remaining:
                chunk = handle.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(chunks(), status_code=status, media_type=content_type, headers=headers)
