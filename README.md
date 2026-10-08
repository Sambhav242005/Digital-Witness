# Digital Witness

Local CCTV preparation and search service following [SPEC.md](SPEC.md). Backend implementation is available; the frontend is owned by the other teammate and is not yet present.

## Start the backend

Install Python 3.12, [uv](https://docs.astral.sh/uv/) and FFmpeg/ffprobe. Run from the repository root:

```bash
uv sync --project backend
PYTHONPATH=backend uv run --project backend uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [interactive API documentation](http://localhost:8000/docs). The frontend origin defaults to `http://localhost:3000`; all media URLs default to `http://localhost:8000`. Environment settings are listed in [backend/.env.example](backend/.env.example). Export settings in your shell or pass an environment file using uv's `--env-file` option; the application does not load `.env` implicitly. `DATA_DIR` is relative to the process working directory. Keep the same working directory and data directory after restart.

Run one server process per data directory. A process lock protects the single persistent worker. Restart fails interrupted queued/running jobs visibly; retry failed recordings or submit a new search. Successful recordings, zones, jobs, vector mappings and searches survive restart. The worker runs independently of HTTP requests and publishes complete indexes/results transactionally. Media is resolved through opaque IDs and supports single byte ranges, including suffix ranges and 416 responses.

## Actual capability status

Preparation, previews, zone validation/storage, queue/lifecycle, retries, recovery, persistence and media delivery run locally with real FFmpeg. The server always reports `mode: "live"`; it has no canned live matches. Gemini chat, Gemini Embedding 2 and verification capabilities start false. Indexing returns `MODEL_UNAVAILABLE` until the Gemini embedding adapter loads. Search additionally requires a validation-derived `RELEVANCE_THRESHOLD`. Unavailable verification preserves semantic results with warnings and `not_checked`. Temporal events and filters remain disabled until P0 acceptance passes.

[Model integration notes](backend/MODEL-NOTES.md) record official sources, API identifiers, runtime APIs, and limitations. Gemini chat and Gemini Embedding 2 both use the same server-side `GEMINI_API_KEY` through the pinned Google SDK. Visual clip samples go to Google for embedding; chat sends conversation and retrieved evidence metadata. No key, raw exception payload or internal media path is returned to the frontend. Both Google adapters passed live API smoke checks with the user-provided key. Full upload/index/search and persistent follow-up chat also ran through the actual HTTP service on generated geometric footage. Automated regression tests continue to use explicit mocked SDK responses.

Gemini 3.5 Flash performs visual decisions on candidate frames using the same backend key. Frames are sent to Google. Decisions are yes/no/uncertain with `probability_yes: null`; no local Laya runtime is required. Live visual smoke checks passed.

To enable the Google adapters, set `GEMINI_API_KEY` only in the backend environment and `LOAD_MODELS=true`. The key is shared by all three Google adapters. Defaults are `gemini-embedding-2` and `gemini-3.5-flash`, configurable through `GEMINI_EMBEDDING_MODEL` and `GEMINI_CHAT_MODEL`. Loading runs in a background thread; health capabilities become true only after successful smoke API requests. These smoke tests make billable requests (two text embeddings, one video embedding one chat function-call check and one visual-decision check). The embedding fingerprint includes provider/model ID, dimension, preprocessing and SDK version; incompatible indexes fail searches instead of comparing incompatible vectors. Hosted model IDs are service identifiers, not immutable local-weight revision guarantees.

`RELEVANCE_THRESHOLD` must be selected on development footage, then evaluated separately. No guessed default threshold is supplied. Readability gates remain provisional heuristics. Gemini decisions do not supply calibrated probabilities. Frame checks establish visible attributes in sampled frames; they do not establish entrance proximity, identity, ownership, intent or temporal events. Cosine scores are not accuracy.

The local ignored environment currently contains the user-supplied key, `LOAD_MODELS=true`, the tested `gemini-3.5-flash` chat selection, and a measured synthetic-development threshold of `0.7633429517975161`. Recalibrate that threshold for real CCTV footage; it is not a production recommendation. The key file has mode 0600 and is excluded from Git. Startup using those local settings is:

```bash
PYTHONPATH=backend uv run --project backend --env-file backend/.env uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Frontend handoff

See [FRONTEND-HANDOFF.md](FRONTEND-HANDOFF.md) for teammate instructions.

[contracts/openapi.json](contracts/openapi.json) is generated from the actual API. [contracts/fixtures](contracts/fixtures) contains complete route/lifecycle/evidence/error examples, visibly described as illustrative. Poll jobs/searches every two seconds; JSON uses the canonical `data` envelope and failures the `error` plus `request_id` envelope. See SPEC.md for the exact integration behavior.

Generate browser-playable synthetic media for fixture URLs:

```bash
PYTHONPATH=backend uv run --project backend python backend/scripts/seed_fixture_media.py
```

This registers fixture **media only**, avoiding synthetic ready recordings or vectors in the live recording library. A frontend fixture client uses the JSON examples; live media URLs resolve to the synthetic 12-second test pattern. No model inference is claimed by those examples.

Live flow: multipart `POST /api/v1/videos` with `file` and `camera_label` → poll preparation job → GET draft video → optionally PUT zones → POST index with `{}` → poll indexing → POST search → poll job/search → play returned source interval and inspect evidence. Maximum upload is 500 MiB/30 minutes. Draft previews work while model capabilities are unavailable.

Chat flow (contract 1.1): `POST /api/v1/chats` with ready `video_ids` → `POST /api/v1/chats/{chat_id}/messages` with `message` → poll chat detail every two seconds until idle/failed. Chats persist across reload/restart. Follow-ups reuse the previous query, selected recordings and filters; for example, “Only show matches after 2 minutes” retains the query and applies recording-relative time from 120 seconds.

Gemini chooses validated `search_video` and `get_search_results` tool calls within the chat's selected recordings. It finishes by selecting actual retrieved result IDs; the backend renders the stored summary, interval and verification reason. This keeps explanation claims tied to returned evidence. Unknown result references cannot publish an answer. Turns have bounded tool loops, one active turn per chat and persistent interruption recovery. Internal chat tasks do not change the public job enums. Generation never replaces temporal rules or frame checks.

Frontend handoff: the existing frontend plan still describes contract 1.0 and lacks chat. The frontend owner should use SPEC.md 1.1 and the generated contracts, adding `health.capabilities.chat` and the chat workflow. Frontend files were not changed.

## Verification

```bash
uv run --project backend python -m pytest backend/tests -q
PYTHONPATH=backend uv run --project backend python backend/scripts/export_contract.py
```

Tests use actual generated MP4 files for FFmpeg and media checks. Search/chat orchestration uses **explicit injected test doubles** in tests only; those results are not model evaluation. Coverage includes schemas/polygons, upload validation, range delivery, duplicate job protection, failed-stage retry, interrupted-worker recovery, atomic index/result publication, filters, unrelated-query empty results, model-version incompatibility, degraded verification, SDK request types, bounded cloud video inputs, persistent chat follow-ups, invalid tool scope and invented-reference rejection. See [backend/ACCEPTANCE.md](backend/ACCEPTANCE.md) for what remains unverified.

Once the model and labeled footage are available, index the development recordings, calibrate a threshold, then measure retrieval on held-out recordings:

```bash
PYTHONPATH=backend uv run --project backend python backend/scripts/calibrate.py /path/to/development-labels.json --output /path/to/calibration.json
# Export RELEVANCE_THRESHOLD from calibration.json and restart the server.
PYTHONPATH=backend uv run --project backend python backend/scripts/evaluate.py /path/to/labels.json --output /path/to/results.json
```

The label shape is documented in that script. It reports interval-overlap recall@5, false-positive candidates, verification outcomes and latency. Empty expected intervals represent unrelated queries. Store footage, labels, evaluation output, databases, vectors, credentials and weights outside Git. Use 3–5 consenting staged videos and at least ten labeled queries; separate development and final evaluation examples.

P0 is not accepted until AC01–AC09 pass on the live model pipeline with the frontend teammate. P1 tracking remains deferred by the agreed delivery order.

## Measured development smoke

On 8 October 2026, two generated four-second recordings (a red square and a blue circle) ran through real upload, preparation, saved zones, Gemini indexing and Range/206 media delivery. Two corresponding visual queries retrieved the expected recordings, and an unrelated bag query returned zero results. This tiny development set had interval-overlap recall@5 1.0 and zero false-positive candidates, with mean polling-observed search latency 2.02 seconds. Preparation and indexing each took about 2.02 seconds as observed through two-second job polls. These measurements include polling delay and are not isolated model latency or CCTV accuracy estimates.

Gemini chat returned a grounded clip explanation and retained the query on a live “after 2 seconds” follow-up. One earlier follow-up attempt failed visibly; resubmission succeeded. Chat generation has bounded retries for upstream failures. Gemini 3.8 Flash smoke attempts returned server errors; the default is the live-tested Gemini 3.5 Flash. Results are in ignored `backend/data/live-smoke-*.json`, and `backend/scripts/live_smoke.py` reproduces the generated-footage preparation/indexing/calibration step with billable API calls. Held-out evaluation, ten labeled CCTV queries, staged Gemini visual evaluation, fresh-browser UI acceptance and P1 remain outstanding.
