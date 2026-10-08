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

Preparation, previews, zone validation/storage, queue/lifecycle, retries, recovery, persistence and media delivery run locally with real FFmpeg. The server always reports `mode: "live"`; it has no canned live matches. Embedding, chat and verification capabilities start false. Indexing returns `MODEL_UNAVAILABLE` until the selected embedding adapter loads. Search additionally requires a validation-derived `RELEVANCE_THRESHOLD`. Unavailable verification preserves semantic results with warnings and `not_checked`. Temporal events and filters remain disabled until P0 acceptance passes.

[Model integration notes](backend/MODEL-NOTES.md) record official sources, API identifiers and limitations. The current selectable setup uses OpenRouter's multimodal embedding endpoint through the pinned OpenAI Python SDK, and Ollama's OpenAI-compatible chat-completions endpoint for chat and frame vision. Keys stay in the backend environment. The OpenRouter free embedding route warns that prompts and outputs may be logged; do not use it with sensitive footage. The Ollama tool-call and image-question-answering smoke requests passed. OpenRouter could not be live-tested because `OPENROUTER_API_KEY` is not configured in the local backend environment. Automated regression tests cover both adapters with fake provider responses.

Gemini 3.5 Flash performs visual decisions on candidate frames using the same backend key. Frames are sent to Google. Decisions are yes/no/uncertain with `probability_yes: null`; no local Laya runtime is required. Live visual smoke checks passed.

For the current setup, set `OPENROUTER_API_KEY` in `backend/.env`, sign in to Ollama on the machine running the backend (or set `CHAT_BASE_URL=https://ollama.com/v1` and `CHAT_API_KEY` for direct Ollama Cloud access), and keep `LOAD_MODELS=true`. The configured models are `nvidia/llama-nemotron-embed-vl-1b-v2:free` and `gemma4:31b-cloud`; `EMBEDDING_PROVIDER`, `OPENROUTER_EMBEDDING_MODEL`, `CHAT_PROVIDER`, `CHAT_BASE_URL`, `CHAT_API_KEY`, and `CHAT_MODEL` are configurable. The OpenRouter adapter samples chronological frames from each 8-second clip and sends them with clip text as one multimodal document to produce one clip vector. This model/provider change requires reindexing recordings; the `/index` endpoint now reindexes ready recordings when their stored fingerprint differs. Health capabilities become true only after adapter smoke requests succeed. Alternatively set `EMBEDDING_PROVIDER=gemini` and `CHAT_PROVIDER=gemini` and configure `GEMINI_API_KEY`; Gemini model variables remain configurable. See `backend/.env.example` for all settings.

`RELEVANCE_THRESHOLD` must be selected on development footage, then evaluated separately. No guessed default threshold is supplied. Readability gates remain provisional heuristics. Gemini decisions do not supply calibrated probabilities. Frame checks establish visible attributes in sampled frames; they do not establish entrance proximity, identity, ownership, intent or temporal events. Cosine scores are not accuracy.

The local ignored environment currently contains the user-supplied key, `LOAD_MODELS=true`, the tested `gemini-3.5-flash` chat selection, and a measured real-footage development threshold of `0.5721176865348145`. It was calibrated on a small public street clip and evaluated on a separate traffic clip; recalibrate for representative CCTV footage. It is not a production recommendation. The key file has mode 0600 and is excluded from Git. Startup using those local settings is:

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

Gemini chooses validated `search_video` and `get_search_results` tool calls within the chat's selected recordings. For visible-detail questions, it invokes frame inspection: Gemini receives actual retrieved images and returns a natural answer with validated frame citations. The backend adds source timestamps and retains evidence links. Dedicated bag checks remain separate from general visual answers. Unknown result references cannot publish an answer. Turns have bounded tool loops, one active turn per chat and persistent interruption recovery. Internal chat tasks do not change the public job enums. Generation never replaces temporal rules or frame checks.

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

Gemini chat returned a grounded clip explanation and retained the query on a live “after 2 seconds” follow-up. One earlier follow-up attempt failed visibly; resubmission succeeded. Chat failures now expose provider status and a bounded cooldown, with one SDK attempt per call. Gemini 3.8 Flash smoke attempts returned server errors; the default is the live-tested Gemini 3.5 Flash. Results are in ignored `backend/data/live-smoke-*.json`, and `backend/scripts/live_smoke.py` reproduces the generated-footage preparation/indexing/calibration step with billable API calls. Held-out evaluation, ten labeled CCTV queries, staged Gemini visual evaluation, fresh-browser UI acceptance and P1 remain outstanding.

## Current integration fixes

The frontend now includes persisted chat and grounded result links. Start it with Node 22.12+ (24 recommended), `cd frontend && npm ci && npm run dev`. Its API URL includes `/api/v1`; default mock mode is false. See frontend/README.md for exact dependency pins and transitive security overrides.

Gemini 429/transient errors use `MODEL_UNAVAILABLE` with safe `provider_status` and `retry_after_sec` details. HTTP 503 errors include Retry-After. Adapter health turns false during cooldown and automatically permits recovery; transient startup smoke failures retry after cooldown. No raw Google payloads are returned. Quota/billing limits still require available Google capacity and cannot be solved by retries.

After calibration on six queries against a public pedestrian recording, all three relevant queries retrieved footage and three unrelated queries were empty. A distinct public traffic clip then passed two relevant and two unrelated holdout queries (recall@5 1.0, zero false-positive candidates in this tiny set). Checks ran with real Gemini embeddings. Visual bag checks were degraded to not_checked because Gemini generation quota was unavailable. These are small public street scenes, not a surveillance accuracy benchmark. Attribution and measurements remain in ignored backend/data/internet-qa; see backend/QA-REPORT.md for the before/after audit.

Visual chat now answers questions such as “Where is the package?” using actual retrieved timestamped images. It describes visible positions without claiming ownership or intent. Greetings and clarifications need no footage search. General visual observations are generated model answers, not calibrated correctness guarantees; inspect the linked frames.
