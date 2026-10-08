from types import SimpleNamespace

import pytest
from PIL import Image

from app.config import Settings
from app.errors import ApiFailure
from app.service import Service


@pytest.fixture
def service(tmp_path, monkeypatch):
    instance = Service(Settings(data_dir=tmp_path, worker_enabled=False), SimpleNamespace(), SimpleNamespace())
    source = tmp_path / "playback.mp4"
    source.write_bytes(b"fixture mapped source")
    with instance.store.transaction() as db:
        url = instance.register_media(db, source, "video", "prepare", "video/mp4")
        instance.store.put(db, "video", "video", {"video_id": "video", "status": "ready"})
        results = [dict(result_id=f"result-{i}", video_id="video", camera_label="Entrance", start_sec=i * 8, end_sec=(i+1)*8, playback_url=url, evidence=[], verification={"status": "not_checked", "basis": "none", "reason": "old"}) for i in range(3)]
        instance.store.put(db, "search", "search", {"search_id": "search", "status": "succeeded", "results": results})
    def frame(source, timestamp, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (320, 240), "red").save(destination)
    monkeypatch.setattr("app.service.media.frame", frame)
    return instance


def test_frames_are_bounded_mapped_and_published_without_claim(service):
    groups = service.get_visual_evidence("search")
    assert len(groups) == 2
    assert sum(len(group["frames"]) for group in groups) == 6
    for group in groups:
        for frame in group["frames"]:
            assert group["start_sec"] <= frame["timestamp_sec"] < group["end_sec"]
            assert frame["path"].is_file()
            assert frame["checks"] == []
    public = service.get("search", "search")
    assert len(public["results"][0]["evidence"]) == 3
    assert "path" not in public["results"][0]["evidence"][0]
    assert public["results"][0]["verification"]["status"] == "not_checked"
    assert "visual question answering" in public["results"][0]["verification"]["reason"]


def test_existing_checked_frames_are_reused(service, monkeypatch):
    initial = service.visual_evidence("result-0")
    with service.store.transaction() as db:
        search = service.store.get(db, "search", "search")
        search["results"][0]["evidence"][0]["checks"] = [{"check_id": "bag_present", "answer": "yes"}]
        search["results"][0]["verification"] = {"status": "supported", "basis": "frame_checks", "reason": "bag"}
        service.store.put(db, "search", "search", search)
    monkeypatch.setattr("app.service.media.frame", lambda *args: pytest.fail("must reuse frames"))
    repeated = service.visual_evidence("result-0")
    assert [f["frame_id"] for f in repeated] == [f["frame_id"] for f in initial]
    assert repeated[0]["checks"][0]["answer"] == "yes"
    assert service.get("search", "search")["results"][0]["verification"]["status"] == "supported"


def test_failed_extraction_is_atomic_and_sanitized(service, monkeypatch):
    calls = 0
    def fail(source, timestamp, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("secret private path")
        destination.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (320, 240)).save(destination)
    monkeypatch.setattr("app.service.media.frame", fail)
    with pytest.raises(ApiFailure) as error:
        service.visual_evidence("result-0")
    assert "secret" not in str(error.value)
    assert service.get("search", "search")["results"][0]["evidence"] == []
    with service.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 1
    assert not list(service.settings.data_dir.glob("attempts/*/*.jpg"))


def test_only_completed_owned_results_and_confined_media(service):
    with pytest.raises(ApiFailure):
        service.get_visual_evidence("search", ["foreign"])
    with pytest.raises(ApiFailure):
        service.get_visual_evidence("search", ["result-0", "result-1", "result-2"])
    with pytest.raises(ValueError):
        service.get_visual_evidence("search", max_frames=7)
    with service.store.transaction() as db:
        search = service.store.get(db, "search", "search")
        search["status"] = "running"
        service.store.put(db, "search", "search", search)
    with pytest.raises(ApiFailure):
        service.visual_evidence("result-0")


def test_mapping_cannot_read_arbitrary_server_paths(service, tmp_path):
    outside = tmp_path.parent / "outside.jpg"
    outside.write_bytes(b"private")
    with service.store.transaction() as db:
        db.execute("UPDATE media SET path=?", (str(outside),))
    with pytest.raises(ApiFailure) as error:
        service.visual_evidence("result-0")
    assert error.value.error["code"] == "MEDIA_NOT_FOUND"
