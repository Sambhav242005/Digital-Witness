"""Transactional metadata and persistent exact cosine vector index.

SQLite stores small JSON documents and clip vectors, never media blobs. All
publication and lifecycle transitions share one BEGIN IMMEDIATE transaction.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid


def identifier(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def encode(value):
    return json.dumps(value, allow_nan=False)


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "witness.sqlite3"
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS media (
                    id TEXT PRIMARY KEY, path TEXT NOT NULL, content_type TEXT NOT NULL,
                    video_id TEXT NOT NULL, attempt_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS clips (
                    id TEXT PRIMARY KEY, video_id TEXT NOT NULL, revision TEXT NOT NULL,
                    body TEXT NOT NULL, vector TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS clips_video ON clips(video_id);
            """)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def get(db, kind, key):
        row = db.execute("SELECT body FROM documents WHERE kind=? AND id=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def put(db, kind, key, body):
        db.execute("INSERT INTO documents VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body", (kind, key, encode(body)))

    @staticmethod
    def all(db, kind):
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM documents WHERE kind=? ORDER BY rowid", (kind,))]

    def recover(self):
        error = {"code": "WORKER_INTERRUPTED", "message": "Processing was interrupted. Retry the recording or submit a new search.", "details": {}}
        with self.transaction() as db:
            for job in self.all(db, "job"):
                if job["status"] not in ("queued", "running"):
                    continue
                job.update(status="failed", stage="failed", error=error, updated_at=now())
                self.put(db, "job", job["job_id"], job)
                kind = "search" if job["kind"] == "search" else "video"
                resource = self.get(db, kind, job["resource_id"])
                if resource:
                    resource.update(status="failed", error=error)
                    if kind == "video":
                        resource["active_job_id"] = None
                    else:
                        resource["results"] = []
                    self.put(db, kind, job["resource_id"], resource)
            for task in self.all(db, 'chat_task'):
                if task['status'] not in ('queued', 'running'):
                    continue
                task['status'] = 'failed'
                self.put(db, 'chat_task', task['turn_id'], task)
                chat = self.get(db, 'chat', task['chat_id'])
                if chat:
                    chat.update(status='failed', active_turn_id=None, error=error, updated_at=now())
                    self.put(db, 'chat', chat['chat_id'], chat)
