"""API orchestration tests use explicit test doubles, never live model fallbacks."""
import json
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import Video, Job, Search, ErrorEnvelope


class TestEmbedding:
    __test__ = False
    available = True
    revision = "test-double-v1"
    def embed_clip(self, path, start, end):
        return [1.0, 0.0]
    def embed_text(self, query):
        return [-1.0, 0.0] if query == "unrelated" else [1.0, 0.0]


class MissingVerification:
    available = False


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path, worker_enabled=False, relevance_threshold=0.5)
    app = create_app(settings, TestEmbedding(), MissingVerification())
    with TestClient(app) as client:
        yield client


@pytest.fixture
def footage(tmp_path):
    path = tmp_path / "input.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=128x96:rate=5", "-t", "9", "-c:v", "mpeg4", "-y", str(path)], check=True)
    return path.read_bytes()


def upload(client, footage):
    response = client.post("/api/v1/videos", files={"file": ("camera.mp4", footage, "video/mp4")}, data={"camera_label": " Entrance "})
    assert response.status_code == 202, response.text
    return response.json()["data"]


def prepared(client, footage):
    data = upload(client, footage)
    assert client.app.state.service.run_one()
    video = client.get("/api/v1/videos/"+data["video"]["video_id"]).json()["data"]
    assert video["status"] == "draft", video
    Video.model_validate(video)
    return video


def ready(client, footage):
    video = prepared(client, footage)
    response = client.post(f'/api/v1/videos/{video["video_id"]}/index', json={})
    assert response.status_code == 202, response.text
    assert client.app.state.service.run_one()
    video = client.get("/api/v1/videos/"+video["video_id"]).json()["data"]
    assert video["status"] == "ready", video
    return video


def test_index_route_reindexes_ready_video_after_embedding_model_change(client,footage):
    video=ready(client,footage)
    adapter=client.app.state.service.embedding
    adapter.revision='new-test-embedding-v2'
    response=client.post(f'/api/v1/videos/{video["video_id"]}/index',json={})
    assert response.status_code==202,response.text
    assert response.json()['data']['video']['status']=='indexing'
    client.app.state.service.run_one()
    updated=client.get('/api/v1/videos/'+video['video_id']).json()['data']
    assert updated['status']=='ready'
    with client.app.state.service.store.transaction() as db:
        revisions={row[0] for row in db.execute('SELECT DISTINCT revision FROM clips WHERE video_id=?',(video['video_id'],))}
    assert revisions=={'new-test-embedding-v2'}


def search(client, video, query="a bag", **kwargs):
    response = client.post("/api/v1/searches", json=dict(query=query, video_ids=[video["video_id"]], **kwargs))
    assert response.status_code == 202, response.text
    search_id = response.json()["data"]["search_id"]
    initial = client.get("/api/v1/searches/"+search_id).json()["data"]
    assert initial["results"] == [] and initial["status"] == "queued"
    assert client.app.state.service.run_one()
    result = client.get("/api/v1/searches/"+search_id).json()["data"]
    Search.model_validate(result)
    assert result["status"] == "succeeded", result
    return result


def test_upload_preparation_media_and_zones(client, footage):
    video = prepared(client, footage)
    assert video["camera_label"] == "Entrance"
    assert video["duration_sec"] == 9
    assert video["active_job_id"] is None
    body = {"zones": [{"name": "Door", "kind": "entrance", "polygon": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}]}]}
    response = client.put(f'/api/v1/videos/{video["video_id"]}/zones', json=body)
    assert response.status_code == 200
    zone = response.json()["data"]["zones"][0]
    assert zone["zone_id"]
    assert client.get(f'/api/v1/videos/{video["video_id"]}').json()["data"]["zones"] == [zone]
    media_path = video["playback_url"].removeprefix("http://localhost:8000")
    full = client.get(media_path)
    part = client.get(media_path, headers={"Range": "bytes=10-29"})
    assert part.status_code == 206 and part.content == full.content[10:30]
    assert part.headers["content-length"] == "20"
    assert client.get(media_path, headers={"Range": f"bytes={len(full.content)}-"}).status_code == 416
    assert client.get(video["thumbnail_url"]).headers["content-type"] == "image/jpeg"


def test_index_search_filters_empty_and_degraded_verification(client, footage):
    first = ready(client, footage)
    second = ready(client, footage)
    result = search(client, first)
    assert result["results"]
    assert result["warnings"][0]["code"] == "VERIFICATION_UNAVAILABLE"
    assert all(r["video_id"] == first["video_id"] for r in result["results"])
    assert all(r["verification"]["status"] == "not_checked" for r in result["results"])
    assert all(r["event_type"] is None for r in result["results"])
    assert search(client, first, "unrelated")["results"] == []
    filtered = search(client, second, time_range={"start_sec": 8, "end_sec": 9})
    assert filtered["results"][0]["start_sec"] == 4  # overlap retains original boundaries
    arbitrary = search(client, first, "red vehicle")
    assert arbitrary["results"][0]["verification"]["status"] == "not_checked"
    assert arbitrary["warnings"] == []
    assert client.put(f'/api/v1/videos/{first["video_id"]}/zones', json={"zones": []}).status_code == 409


def test_duplicate_index_atomic_and_retry_index_cleanup(client, footage):
    video = prepared(client, footage)
    url = f'/api/v1/videos/{video["video_id"]}/index'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(url, json={}), range(2)))
    assert sorted(r.status_code for r in responses) == [202, 409]
    service = client.app.state.service
    service.embedding.embed_clip = lambda *args: [float("nan"), 0]
    service.run_one()
    failed = client.get(f'/api/v1/videos/{video["video_id"]}').json()["data"]
    assert failed["status"] == "failed" and failed["playback_url"]
    with service.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM clips").fetchone()[0] == 0
    service.embedding = TestEmbedding()
    retry = client.post(f'/api/v1/videos/{video["video_id"]}/retry', json={})
    assert retry.status_code == 202
    assert retry.json()["data"]["job"]["kind"] == "index_video"
    service.run_one()
    with service.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM clips").fetchone()[0] == 3
    assert client.get(f'/api/v1/videos/{video["video_id"]}').json()["data"]["status"] == "ready"


def test_failed_preparation_retry(client):
    data = upload(client, b"not a video")
    client.app.state.service.run_one()
    video_id = data["video"]["video_id"]
    failure = client.get(f"/api/v1/videos/{video_id}").json()["data"]
    assert failure["status"] == "failed"
    assert failure["error"]["code"] == "MEDIA_DECODE_FAILED"
    retry = client.post(f"/api/v1/videos/{video_id}/retry", json={})
    assert retry.status_code == 202
    assert retry.json()["data"]["job"]["kind"] == "prepare_video"
    assert client.post(f"/api/v1/videos/{video_id}/retry", json={}).status_code == 409


def test_attempt_directory_failure_terminates_job(client):
    data = upload(client,b'undecoded')
    (client.app.state.service.settings.data_dir/'attempts').write_text('blocks directory creation')
    assert client.app.state.service.run_one()
    job = client.get('/api/v1/jobs/'+data['job']['job_id']).json()['data']
    assert job['status']=='failed'
    video = client.get('/api/v1/videos/'+data['video']['video_id']).json()['data']
    assert video['status']=='failed' and video['active_job_id'] is None


@pytest.mark.parametrize("route,code", [("videos", "VIDEO_NOT_FOUND"), ("jobs", "JOB_NOT_FOUND"), ("searches", "SEARCH_NOT_FOUND"), ("media", "MEDIA_NOT_FOUND")])
def test_missing_resource_errors(client, route, code):
    response = client.get(f"/api/v1/{route}/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == code
    ErrorEnvelope.model_validate(response.json())


def test_validation_and_unavailable_errors(client, footage):
    assert client.get("/api/v1/videos?limit=0").status_code == 422
    assert client.post("/api/v1/videos", files={"file": ("x.avi", b"abc", "video/avi")}, data={"camera_label": "X"}).status_code == 415
    assert client.post("/api/v1/videos", files={"file": ("x.mp4", b"abc", "video/mp4")}, data={"camera_label": " "}).status_code == 422
    video = prepared(client, footage)
    invalid = client.put(f'/api/v1/videos/{video["video_id"]}/zones', json={"zones": [{"name":"X", "kind":"entrance", "polygon": []}]})
    assert invalid.json()["error"]["code"] == "INVALID_ZONE"
    assert client.post("/api/v1/searches", json={"query": "bag", "video_ids": [video["video_id"]]}).status_code == 409
    event = client.post("/api/v1/searches", json={"query": "bag", "video_ids": [video["video_id"]], "event_types": ["person_entered"]})
    assert event.status_code == 422 and event.json()["error"]["code"] == "UNSUPPORTED_EVENT_TYPE"
    client.app.state.service.embedding.available = False
    assert client.post(f'/api/v1/videos/{video["video_id"]}/index', json={}).status_code == 503


def test_queue_and_upload_limit_cleanup(client):
    service = client.app.state.service
    service.settings.max_queued_jobs = 1
    upload(client, b"not yet decoded")
    response = client.post("/api/v1/videos", files={"file": ("x.mp4", b"abc", "video/mp4")}, data={"camera_label": "X"})
    assert response.status_code == 429 and response.headers["retry-after"] == "2"
    assert len(list((service.settings.data_dir / "uploads").iterdir())) == 1
    service.settings.max_upload_bytes = 3
    response = client.post("/api/v1/videos", files={"file": ("x.mp4", b"abcd", "video/mp4")}, data={"camera_label": "X"})
    assert response.status_code == 413
    assert len(list((service.settings.data_dir / "uploads").iterdir())) == 1


def test_restart_visible_failure_and_persistence(tmp_path, footage):
    settings = Settings(data_dir=tmp_path, worker_enabled=False, relevance_threshold=.5)
    app = create_app(settings, TestEmbedding(), MissingVerification())
    with TestClient(app) as client:
        data = upload(client, footage)
    with TestClient(create_app(settings, TestEmbedding(), MissingVerification())) as client:
        video = client.get('/api/v1/videos/'+data["video"]["video_id"]).json()["data"]
        assert video["status"] == "failed" and video["active_job_id"] is None
        assert video["error"]["code"] == "WORKER_INTERRUPTED"
        job = client.get('/api/v1/jobs/'+data["job"]["job_id"]).json()["data"]
        assert job["status"] == "failed" and job["progress_pct"] < 100
        retry = client.post('/api/v1/videos/'+video["video_id"]+'/retry', json={})
        assert retry.status_code == 202
        client.app.state.service.run_one()
        assert client.get('/api/v1/videos/'+video["video_id"]).json()["data"]["status"] == "draft"


def test_model_revision_mismatch_fails_search(client, footage):
    video = ready(client, footage)
    client.app.state.service.embedding.revision = "changed"
    response = client.post("/api/v1/searches", json={"query":"bag", "video_ids":[video["video_id"]]})
    search_id = response.json()["data"]["search_id"]
    client.app.state.service.run_one()
    search = client.get("/api/v1/searches/"+search_id).json()["data"]
    assert search["status"] == "failed" and search["results"] == []


def test_poor_frames_never_call_verifier_or_claim_support(client, footage, monkeypatch):
    class Verification:
        available = True
        def check(self, *args):
            raise AssertionError('Poor frames must not run inference')
    client.app.state.service.verification = Verification()
    monkeypatch.setattr('app.ai.verification_adapter.image_quality', lambda _: 'poor')
    video = ready(client, footage)
    result = search(client, video)
    assert result['warnings'] == []
    for candidate in result['results']:
        assert candidate['verification']['status'] == 'uncertain'
        assert len(candidate['evidence']) == 3
        for frame in candidate['evidence']:
            assert candidate['start_sec'] <= frame['timestamp_sec'] < candidate['end_sec']
            assert frame['checks'][0]['probability_yes'] is None
            assert client.get(frame['image_url']).status_code == 200


def test_verification_runtime_failure_degrades_search(client, footage, monkeypatch):
    class Verification:
        available = True
        def check(self, *args):
            raise RuntimeError('test inference failure')
    client.app.state.service.verification = Verification()
    monkeypatch.setattr('app.ai.verification_adapter.image_quality', lambda _: 'usable')
    result = search(client, ready(client, footage))
    assert result['warnings'][0]['code'] == 'VERIFICATION_UNAVAILABLE'
    assert all(r['verification']['status'] == 'not_checked' and r['evidence'] == [] for r in result['results'])


def test_gemini_native_answers_publish_null_probability_with_evidence(client,footage,monkeypatch):
    class Verification:
        available = True
        def check(self,*args):
            return {'answer':'yes','probability_yes':None}
    client.app.state.service.verification = Verification()
    monkeypatch.setattr('app.ai.verification_adapter.image_quality',lambda _: 'usable')
    result=search(client,ready(client,footage))
    assert result['results'][0]['verification']['status']=='supported'
    assert all(c['probability_yes'] is None and c['answer']=='yes' for r in result['results'] for f in r['evidence'] for c in f['checks'])


def test_chunked_oversize_upload_returns_413(client):
    boundary = 'test-boundary'
    header = ('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="x.mp4"\r\nContent-Type: video/mp4\r\n\r\n').encode()
    client.app.state.service.settings.max_upload_bytes = 3
    def body():
        yield header
        yield b'x' * (1024*1024+4)
        yield ('\r\n--'+boundary+'--\r\n').encode()
    response = client.post('/api/v1/videos',content=body(),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    assert response.status_code == 413, response.text


def test_health_live_models_disabled_and_cors(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, worker_enabled=False))) as client:
        health = client.get('/api/v1/health').json()["data"]
        assert health["mode"] == "live"
        assert not any(health["capabilities"].values())
        preflight = client.options('/api/v1/videos', headers={"Origin":"http://localhost:3000", "Access-Control-Request-Method":"POST"})
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert client.get('/openapi.json').status_code == 200


def test_real_worker_returns_promptly_and_completes(tmp_path, footage):
    import time
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        data = upload(client, footage)
        for _ in range(100):
            job = client.get('/api/v1/jobs/'+data["job"]["job_id"]).json()["data"]
            Job.model_validate(job)
            if job["status"] in ("succeeded", "failed"):
                break
            time.sleep(.05)
        assert job["status"] == "succeeded", job
