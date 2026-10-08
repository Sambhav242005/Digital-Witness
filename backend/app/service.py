from pathlib import Path
from threading import Event, Thread
import logging
import math
import shutil

from .config import Settings
from .errors import ApiFailure
from .store import Store, identifier, now, encode
from . import media
from .schemas import FrameCheck

logger = logging.getLogger(__name__)


def normalized(values):
    values = [float(x) for x in values]
    norm = math.hypot(*values)
    if not values or not all(math.isfinite(x) for x in values) or not math.isfinite(norm) or norm <= 0:
        raise ValueError("Invalid embedding")
    return [x/norm for x in values]


class Service:
    def __init__(self, settings: Settings, embedding, verification):
        self.settings, self.embedding, self.verification = settings, embedding, verification
        self.store = Store(settings.data_dir)
        self.stop = Event()
        self.wakeup = Event()
        self.thread = None

    def start(self):
        # A process lock prevents a second server from failing the first worker's jobs.
        import fcntl
        self.lock = (self.settings.data_dir / "worker.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("Run exactly one backend server per DATA_DIR") from None
        self.store.recover()
        with self.store.transaction() as db:
            interrupted = [j["job_id"] for j in self.store.all(db, "job") if j["status"] == "failed"]
        for job_id in interrupted:
            shutil.rmtree(self.settings.data_dir / "attempts" / job_id, ignore_errors=True)
        if self.settings.worker_enabled:
            self.thread = Thread(target=self.run, name="witness-worker", daemon=True)
            self.thread.start()

    def close(self):
        self.stop.set()
        self.wakeup.set()
        if self.thread:
            self.thread.join()  # Finish current transaction before releasing ownership.
        self.lock.close()

    def require(self, db, kind, key):
        item = self.store.get(db, kind, key)
        if item is None:
            raise ApiFailure(404, f"{kind.upper()}_NOT_FOUND", f"The requested {kind} does not exist.")
        return item

    def get(self, kind, key):
        with self.store.transaction() as db:
            item = self.require(db, kind, key)
        return self.public(item)

    @staticmethod
    def public(item):
        return {k: v for k, v in item.items() if not k.startswith("_")}

    def job(self, db, kind, resource_id):
        queued = sum(j["status"] == "queued" for j in self.store.all(db, "job")) + sum(t["status"] == "queued" for t in self.store.all(db, "chat_task"))
        if queued >= self.settings.max_queued_jobs:
            raise ApiFailure(429, "QUEUE_FULL", "The processing queue is full. Try again shortly.")
        stamp, job_id = now(), identifier("job")
        job = dict(job_id=job_id, kind=kind, resource_id=resource_id, status="queued", stage="queued", progress_pct=0, created_at=stamp, updated_at=stamp, error=None)
        self.store.put(db, "job", job_id, job)
        return job

    def upload(self, source, filename, camera_label):
        with self.store.transaction() as db:
            video_id = identifier("vid")
            job = self.job(db, "prepare_video", video_id)
            video = dict(video_id=video_id, filename=filename, camera_label=camera_label, status="preparing", created_at=now(), duration_sec=None, width=None, height=None, playback_url=None, thumbnail_url=None, zones=[], active_job_id=job["job_id"], error=None, _source=str(source), _prepared=False)
            self.store.put(db, "video", video_id, video)
        self.wakeup.set()
        return dict(video=self.public(video), job=job)

    def kickoff(self, video_id, retry=False):
        with self.store.transaction() as db:
            video = self.require(db, "video", video_id)
            if video["active_job_id"]:
                raise ApiFailure(409, "JOB_ALREADY_RUNNING", "This recording already has an active job.")
            if video["status"] != ("failed" if retry else "draft"):
                raise ApiFailure(409, "INVALID_STATE", "Retry requires a failed recording; indexing requires a draft recording.")
            kind = "prepare_video" if retry and not video["_prepared"] else "index_video"
            if kind == "index_video" and not self.embedding.available:
                raise ApiFailure(503, "MODEL_UNAVAILABLE", "The embedding model is unavailable. Configure and load the real model.")
            job = self.job(db, kind, video_id)
            video.update(status="preparing" if kind == "prepare_video" else "indexing", active_job_id=job["job_id"], error=None)
            self.store.put(db, "video", video_id, video)
        self.wakeup.set()
        return dict(video=self.public(video), job=job)

    def zones(self, video_id, zones):
        with self.store.transaction() as db:
            video = self.require(db, "video", video_id)
            if video["status"] != "draft" and not (video["status"] == "failed" and video["_prepared"]):
                raise ApiFailure(409, "INVALID_STATE", "Zones can be replaced only after preparation and before successful indexing.")
            video["zones"] = [dict(zone_id=identifier("zone"), **z) for z in zones]
            self.store.put(db, "video", video_id, video)
        return self.public(video)

    def search(self, request):
        if request.get("event_types"):
            raise ApiFailure(422, "UNSUPPORTED_EVENT_TYPE", "Temporal event filters are unavailable in P0.")
        with self.store.transaction() as db:
            videos = [self.require(db, "video", key) for key in request["video_ids"]]
            for video in videos:
                if video["status"] != "ready":
                    raise ApiFailure(409, "VIDEO_NOT_READY", "Wait for indexing to finish before searching.", {"video_id": video["video_id"]})
            time_range = request.get("time_range")
            if time_range and time_range["end_sec"] > videos[0]["duration_sec"]:
                raise ApiFailure(422, "VALIDATION_ERROR", "Time range must fit the recording duration.")
            if not self.embedding.available or self.settings.relevance_threshold is None:
                raise ApiFailure(503, "MODEL_UNAVAILABLE", "Search requires a loaded embedding model and a validation-derived RELEVANCE_THRESHOLD.")
            search_id = identifier("search")
            job = self.job(db, "search", search_id)
            search = dict(search_id=search_id, job_id=job["job_id"], status="queued", query=request["query"], video_ids=request["video_ids"], created_at=now(), warnings=[], results=[], error=None, _request=request)
            self.store.put(db, "search", search_id, search)
        self.wakeup.set()
        return dict(search_id=search_id, job=job)

    def register_media(self, db, path, video_id, attempt, content_type):
        key = identifier("media")
        db.execute("INSERT INTO media VALUES(?,?,?,?,?)", (key, str(path), content_type, video_id, attempt))
        return f"{self.settings.public_base_url}/api/v1/media/{key}"

    def progress(self, job_id, stage, percentage):
        with self.store.transaction() as db:
            job = self.require(db, "job", job_id)
            job.update(stage=stage, progress_pct=max(job["progress_pct"], min(99, percentage)), updated_at=now())
            self.store.put(db, "job", job_id, job)

    def run(self):
        while not self.stop.is_set():
            if not self.run_one():
                self.wakeup.wait(0.5)
                self.wakeup.clear()

    def run_one(self, jobs_only=False):
        with self.store.transaction() as db:
            job = next((j for j in self.store.all(db, "job") if j["status"] == "queued"), None)
            if job is not None:
                job.update(status="running", updated_at=now())
                self.store.put(db, "job", job["job_id"], job)
            if job is not None and job["kind"] == "search":
                search = self.require(db, "search", job["resource_id"])
                search["status"] = "running"
                self.store.put(db, "search", search["search_id"], search)
        if job is None:
            return self.chat.run_one() if not jobs_only and hasattr(self, 'chat') else False
        directory = self.settings.data_dir / "attempts" / job["job_id"]
        try:
            directory.mkdir(parents=True, exist_ok=True)
            if job["kind"] == "prepare_video":
                self.prepare(job, directory)
            elif job["kind"] == "index_video":
                self.index(job, directory)
            else:
                self.retrieve(job, directory)
        except Exception as exc:
            code = exc.code if isinstance(exc, media.MediaError) else {"prepare_video": "MEDIA_DECODE_FAILED", "index_video": "INDEXING_FAILED", "search": "SEARCH_FAILED"}[job["kind"]]
            message = exc.message if isinstance(exc, media.MediaError) else "Processing failed. Check backend configuration and retry."
            logger.error("job=%s kind=%s failed=%s", job["job_id"], job["kind"], code)
            error = dict(code=code, message=message, details={})
            with self.store.transaction() as db:
                current = self.require(db, "job", job["job_id"])
                current.update(status="failed", stage="failed", updated_at=now(), error=error)
                self.store.put(db, "job", current["job_id"], current)
                kind = "search" if job["kind"] == "search" else "video"
                resource = self.require(db, kind, job["resource_id"])
                resource.update(status="failed", error=error)
                if kind == "video":
                    resource["active_job_id"] = None
                else:
                    resource["results"] = []
                self.store.put(db, kind, job["resource_id"], resource)
            shutil.rmtree(directory, ignore_errors=True)
        return True

    def complete(self, db, job):
        job.update(status="succeeded", stage="complete", progress_pct=100, updated_at=now(), error=None)
        self.store.put(db, "job", job["job_id"], job)

    def prepare(self, job, directory):
        self.progress(job["job_id"], "preparing", 1)
        with self.store.transaction() as db:
            video = self.require(db, "video", job["resource_id"])
        prepared = media.prepare(Path(video["_source"]), directory)
        with self.store.transaction() as db:
            video.update(duration_sec=prepared["duration_sec"], width=prepared["width"], height=prepared["height"], _prepared=True, _playback=str(prepared["playback_path"]), status="draft", active_job_id=None, error=None)
            video["playback_url"] = self.register_media(db, prepared["playback_path"], video["video_id"], job["job_id"], "video/mp4")
            video["thumbnail_url"] = self.register_media(db, prepared["thumbnail_path"], video["video_id"], job["job_id"], "image/jpeg")
            self.store.put(db, "video", video["video_id"], video)
            self.complete(db, job)

    def index(self, job, directory):
        self.progress(job["job_id"], "embedding", 1)
        with self.store.transaction() as db:
            video = self.require(db, "video", job["resource_id"])
        clips = []
        revision = getattr(self.embedding, "fingerprint", self.embedding.revision)
        for i, (start, end) in enumerate(media.windows(video["duration_sec"])):
            path = directory / f"clip-{i}.jpg"
            media.frame(Path(video["_playback"]), (start+end)/2, path)
            vector = normalized(self.embedding.embed_clip(Path(video["_playback"]), start, end))
            if clips and len(vector) != len(clips[0][1]):
                raise ValueError("Embedding dimension changed")
            clips.append((dict(clip_id=identifier("clip"), video_id=video["video_id"], start_sec=start, end_sec=end, _thumbnail=str(path)), vector))
            self.progress(job["job_id"], "embedding", 1+95*(i+1)/len(media.windows(video["duration_sec"])))
        with self.store.transaction() as db:
            db.execute("DELETE FROM clips WHERE video_id=?", (video["video_id"],))
            for clip, vector in clips:
                clip["thumbnail_url"] = self.register_media(db, Path(clip.pop("_thumbnail")), video["video_id"], job["job_id"], "image/jpeg")
                db.execute("INSERT INTO clips VALUES(?,?,?,?,?)", (clip["clip_id"], video["video_id"], revision, encode(clip), encode(vector)))
            video.update(status="ready", active_job_id=None, error=None)
            self.store.put(db, "video", video["video_id"], video)
            self.complete(db, job)

    def retrieve(self, job, directory):
        import json
        self.progress(job["job_id"], "retrieving", 1)
        with self.store.transaction() as db:
            search = self.require(db, "search", job["resource_id"])
            request = search["_request"]
            videos = {key: self.require(db, "video", key) for key in request["video_ids"]}
            rows = list(db.execute("SELECT * FROM clips WHERE video_id IN (%s)" % ",".join("?" for _ in videos), list(videos)))
        query = normalized(self.embedding.embed_text(request["query"]))
        candidates = []
        for row in rows:
            clip, vector = json.loads(row["body"]), json.loads(row["vector"])
            if row["revision"] != getattr(self.embedding, "fingerprint", self.embedding.revision) or len(vector) != len(query):
                raise ValueError("Index model version incompatible; reindex required")
            interval = request.get("time_range")
            if interval and not (clip["start_sec"] < interval["end_sec"] and clip["end_sec"] > interval["start_sec"]):
                continue
            score = max(-1, min(1, sum(a*b for a,b in zip(query, vector))))
            if score >= self.settings.relevance_threshold:
                candidates.append((score, clip))
        candidates.sort(key=lambda pair: (-pair[0], pair[1]["video_id"], pair[1]["start_sec"]))
        # Keep the strongest original interval from overlapping semantic windows.
        # Without a temporal event identity, do not merge into an invented span.
        selected = []
        for score, clip in candidates:
            if any(c["video_id"] == clip["video_id"] and c["start_sec"] < clip["end_sec"] and c["end_sec"] > clip["start_sec"] for _,c in selected):
                continue
            selected.append((score, clip))
            if len(selected) == request.get("limit", 10):
                break
        self.progress(job["job_id"], "verifying", 50)
        results, warnings = [], []
        from .ai.verification_adapter import checks_for_query, image_quality, aggregate_checks, answer_for_probability
        checks = checks_for_query(request["query"])
        if checks and not self.verification.available:
            warnings.append(dict(code="VERIFICATION_UNAVAILABLE", message="Frame verification is unavailable; semantic candidates remain unverified."))
        evidence_media = []
        for number, (score, clip) in enumerate(selected):
            video = videos[clip["video_id"]]
            evidence = []
            reason = "This query has no supported visual check. Temporal actions and spatial claims are unverified."
            verification = dict(status="not_checked", basis="none", reason=reason)
            if checks and not self.verification.available:
                verification["reason"] = "Frame verification is unavailable. This is a semantic candidate only."
            elif checks and number < 10:
                try:
                    for k, fraction in enumerate((0.2, 0.5, 0.8)):
                        timestamp = clip["start_sec"] + fraction * (clip["end_sec"]-clip["start_sec"])
                        path = directory / f"evidence-{number}-{k}.jpg"
                        media.frame(Path(video["_playback"]), timestamp, path)
                        quality = image_quality(path)
                        frame_checks = []
                        for check in checks:
                            check_id, question = check["check_id"], check["question"]
                            decision = self.verification.check(path, check_id, question) if quality == "usable" else None
                            if isinstance(decision, dict):
                                checked = FrameCheck.model_validate(dict(check_id=check_id,question=question,answer=decision.get('answer'),probability_yes=decision.get('probability_yes')))
                            else:
                                probability = decision
                                if probability is not None and (not math.isfinite(probability) or not 0 <= probability <= 1):
                                    raise ValueError("Invalid probability")
                                answer = answer_for_probability(probability, self.settings.verification_yes_threshold, self.settings.verification_no_threshold)
                                checked = FrameCheck(check_id=check_id,question=question,answer=answer,probability_yes=probability)
                            frame_checks.append(checked.model_dump())
                        image_id = identifier("media")
                        evidence_media.append((image_id, str(path), "image/jpeg", clip["video_id"], job["job_id"]))
                        evidence.append(dict(timestamp_sec=timestamp, image_url=f"{self.settings.public_base_url}/api/v1/media/{image_id}", quality=quality, checks=frame_checks))
                    verification = aggregate_checks(evidence)
                except Exception:
                    evidence = []
                    verification = dict(status="not_checked", basis="none", reason="Frame verification failed; no visual claim is made.")
                    if not any(w["code"] == "VERIFICATION_UNAVAILABLE" for w in warnings):
                        warnings.append(dict(code="VERIFICATION_UNAVAILABLE", message="Frame verification failed for one or more candidates."))
            elif checks:
                verification["reason"] = "This candidate is outside the first ten candidates selected for visual checking."
            summary = "Semantic candidate clip. Review the recording; identity, ownership, intent and temporal events are unverified."
            if verification["status"] == "supported":
                summary = "Sampled frames support the stated visible attribute only. Spatial and temporal claims remain unverified."
            results.append(dict(result_id=identifier("result"), video_id=clip["video_id"], camera_label=video["camera_label"], start_sec=clip["start_sec"], end_sec=clip["end_sec"], thumbnail_url=clip["thumbnail_url"], playback_url=video["playback_url"], summary=summary, event_type=None, zone_id=None, retrieval_score=score, verification=verification, evidence=evidence))
        self.progress(job["job_id"], "finalizing", 99)
        with self.store.transaction() as db:
            for entry in evidence_media:
                db.execute("INSERT INTO media VALUES(?,?,?,?,?)", entry)
            search.update(status="succeeded", results=results, warnings=warnings, error=None)
            self.store.put(db, "search", search["search_id"], search)
            self.complete(db, job)
