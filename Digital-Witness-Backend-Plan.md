# Digital Witness — Backend and AI Developer Plan

Owner: Person 2 • Contract: v1.1 • Date: 8 October 2026

## 1. Your goal

Deliver one service that owns video preparation, persistence, background processing, Gemini Embedding 2 retrieval, Gemini visual checks, and browser-compatible media. The frontend developer must be able to implement the UI entirely from your OpenAPI and fixtures.

Read [SPEC.md](SPEC.md) first; it controls route names, response envelopes, lifecycle and semantics. Keep [Digital-Witness-SRS.md](Digital-Witness-SRS.md) synchronized as the companion requirements document. Coordinate with [Digital-Witness-Frontend-Plan.md](Digital-Witness-Frontend-Plan.md). You own backend and AI because this team has only two developers.

## 2. Stack and internal boundaries

Use Python + FastAPI + Pydantic; FFmpeg/ffprobe for media; SQLite for metadata; persistent local vector index for retrieval; one background worker. Pin versions after smoke-testing the models. Keep the model adapters independent so UI/API development can proceed while adapters load.

```text
backend/app/
  api/                     # routes and error envelope handlers
  schemas/                 # canonical Pydantic wire schemas
  services/                # video/search/job orchestration
  workers/                 # persisted queue and execution
  ai/embedding_adapter.py  # Gemini Embedding 2
  ai/verification_adapter.py # Gemini
  ai/tracking_adapter.py   # P1 detector + tracker
  events/                  # P1 geometry and temporal rules
  storage/                 # metadata, vectors and media mappings
backend/tests/             # contract, lifecycle and integration checks
contracts/openapi.json
contracts/fixtures/
```

Configuration proposal: FRONTEND_ORIGIN, PUBLIC_BASE_URL, DATA_DIR, DEVICE, GEMINI_API_KEY, GEMINI_EMBEDDING_MODEL, GEMINI_CHAT_MODEL, GEMINI_VERIFICATION_MODEL, MAX_QUEUED_JOBS=20. HTTP server defaults to port 8000. The Next.js frontend runs at http://localhost:3000; set FRONTEND_ORIGIN to that origin for local CORS. Browser requests, including uploads, go directly to FastAPI. Do not assume the browser can reach container-internal hostnames. Model credentials remain on the server.

## 3. Build in this order

### B1 — Freeze the contract and unblock frontend

Implement all SRS schemas and standard exception handlers first. Export OpenAPI and complete fixtures with actual nullable fields/enums. Publish health capabilities. Give frontend representative bodies for every route, plus live dev media URLs that support seeking.

Create a clearly labelled mock mode if useful. In live mode, unavailable models return an explicit error or degraded capability; never substitute canned matches silently.

Deliverable: frontend can develop every screen without waiting for inference.

### B2 — Implement preparation, media and jobs

1. Receive multipart upload with exact keys `file`, `camera_label`; stream bytes to a generated internal path while enforcing the size cap.
2. Store preparing Video and queued preparation Job before responding 202.
3. Probe actual media, reject malformed/over-duration content, produce browser-playable MP4 if needed, extract thumbnail and metadata.
4. Publish prepared media and mark video draft. Support byte ranges on ID-mapped media.
5. Implement list/detail, job detail, zone validation, index kickoff and failed-stage retry.
6. Persist lifecycle changes; interrupted jobs become failed on startup. Make state transitions transaction-safe so double requests cannot launch duplicate jobs.

Deliverable: real upload → preview → draft works through frontend; seek works before full download.

### B3 — Get one real embedding search working

Perform a model smoke test before a long indexing run: embed a short clip and two text queries; verify expected shape, finite values and plausible differences. Record tested model revision, environment and device.

Indexing algorithm:
1. Generate 8-second windows at a 4-second stride, retaining final partial window.
2. Produce clip/frame inputs using the model's supported processor, preserving original seconds.
3. Embed clips with Gemini Embedding 2, normalize consistently, and store clip_id → vector mapping with model revision.
4. Store thumbnails and clip boundaries; optional observation templates are supplementary.
5. Atomically publish the complete index and mark ready. Failed attempts must not leave queryable partial indexes.

Query algorithm:
1. Validate query, ready video IDs, time range and event filters.
2. Create Search and Job; return 202 promptly.
3. Embed text using the model's documented retrieval prompt configuration.
4. Search only the selected ready recordings and applicable filters.
5. Merge duplicate overlapping candidate windows while keeping distinct events separate.
6. Apply validation-derived relevance threshold; permit no results. Retain score as cosine similarity, not a probability.
7. Select final candidates for verification and assemble the exact SearchResult schema.

Deliverable: real query retrieves real footage even before temporal event inference exists.

### B4 — Add Gemini checks and truthful results

Create an allowlisted query-to-check mapping. Initial checks: `bag_present`, `person_carrying_bag`. Unmatched queries remain valid semantic searches but have `not_checked` verification. Do not use a model-dependent freeform JSON generator merely to parse these first checks.

For each top candidate, sample up to 3 representative frames within actual interval. Check readability/quality, then call Gemini with explicit image questions. Keep structured yes/no/uncertain answers and source timestamps; set probability_yes to null because generated answers provide no calibrated class probability. Validate check behavior and readability thresholds on staged footage.

Verification rules:
- Frame answers can support visible attributes only.
- Contradictory or weak evidence yields contradicted or uncertain, not a confident summary.
- Unsupported checks yield not_checked with reason.
- If Gemini is unavailable, preserve semantic search results with warnings and not_checked.
- Do not turn “bag visible” into “person abandoned bag.” Use temporal rules for that claim.
- Evidence must come from the selected video and valid time interval.

Use deterministic templates for summaries. Example: “A sampled frame appears to show a person carrying a bag.” Generate no identity, ownership or intent claim.

Deliverable: evidence-backed frame checks displayed through frontend, with no contract change.

### B5 — Add detection/tracking and temporal events only after P0

Choose and pin a detector with suitable person/bag classes and a compatible tracker. This is an additional component; neither embedding retrieval nor Gemini supplies persistent object identity. Track IDs are local to a recording and are not real-world person identities.

Run detection at an independently chosen sampling rate sufficient for movement; sparse embedding samples are not automatically adequate for tracking. Maintain timestamps and track gaps. Implement point-in-polygon against normalized entrance geometry.

Implement SRS rules for `person_entered` and `possible_unattended_bag`. Track bag stationarity, prior person proximity, departure, persistence and missing observations. Keep rule parameters configurable and retain trace evidence internally. If tracking is broken or occluded, return uncertainty rather than infer abandonment.

Persist events linked to clips, tracks and zone ID. Advertise enabled event types only after their tests pass. Event-filtered searches retrieve from those events; semantic-only matches do not masquerade as rule-detected events. This milestone extends capability values without renaming response fields.

Deliverable: temporal evidence for the demo cases and negative-case tests.

## 4. Data you must persist

| Entity | Minimum internal data |
|---|---|
| Video | ID, filename, camera label, status, metadata, timestamps, active job, error, prepared-stage flag |
| Media | Opaque ID, internal path, content type, video association |
| Zone | ID, video ID, kind, normalized polygon |
| Job | ID, kind, resource ID, state, stage, progress, timestamps, error |
| Clip | ID, video ID, start/end, thumbnail, embedding version/index reference |
| Search | ID, request, job ID, state, result snapshot, warnings, error |
| Evidence | Search/result association, timestamp, image ID, quality and model checks |
| Event, P1 | Video/clip/zone/track references, event type, boundaries, rule version and evidence |

Public Video and Search shapes remain exactly as specified even if internal tables have additional fields. Persistence is required across application restart. Keep media and index outputs tied to their attempt/version so cleanup cannot delete published outputs.

## 5. API and reliability details

- Implement every endpoint and error behavior in SRS sections 7–8.
- Override framework validation responses to use the shared error envelope.
- Return absolute public media URLs and support Range/206/416 correctly.
- Use a persisted queue rather than tying inference lifetime to one HTTP request.
- Bound GPU/model concurrency; return QUEUE_FULL when the waiting limit is reached.
- Retry cleans partial artifacts and writes a fresh job; no duplicate vectors or duplicated events.
- Search results and terminal status commit together. GET search returns results only after success.
- Preserve ranking order; frontend must not need undocumented reranking.
- Log request IDs, job IDs, processing stage and errors without dumping private frames or credentials.
- Health exposes actual capabilities. P0 temporal_events is false and supported_event_types is empty.
- No automatic silent mock fallback if model loading fails.

## 6. Model integration notes

Review the actual model cards and compatible runtime examples while implementing:
- https://ai.google.dev/gemini-api/docs/embeddings
- https://ai.google.dev/gemini-api/docs/image-understanding

Gemini Embedding 2: use the Google API with direct visual clip/frame input, matching dimensions and consistent normalization. Use the documented retrieval query prefix rather than the unsupported task_type field. Store API model identifier, dimensions and preprocessing version with each index. Gemini chat uses the same GEMINI_API_KEY and backend search tools; Gemini visual checks use the same key and default `gemini-3.5-flash` through GEMINI_VERIFICATION_MODEL. Validate model access and requests before advertising capabilities. Footage samples sent for embedding leave the local machine for Google processing.

Gemini visual verification: single-image allowlisted decisions parsed from structured yes/no/uncertain output into FrameCheck, with probability_yes:null. This adapter supplies narrow visual checks rather than captions, bounding boxes or temporal tracking. Check image quality separately. Run a small controlled evaluation before describing its answers as reliable CCTV verification.

Do not combine a clip's embedding similarity and a frame's answer probability into an unexplained “confidence.” Keep both semantically distinct. Measured benchmarks, model-loading time and peak memory belong in README after testing.

## 7. Handoffs and integration checkpoints

| Checkpoint | Give frontend | Joint verification |
|---|---|---|
| Contract ready | OpenAPI + fixtures + error examples | Types, field names and nullability match |
| Media ready | Upload/video/job endpoints + real media | Browser preview and fresh seek work |
| Index ready | Zone/index/retry behavior | UI reaches ready without manual DB edits |
| Search ready | Real search/evidence responses | Query → candidate → exact timestamp |
| P1 ready | Health capability change | Temporal labels and filters behave correctly |

For every shared contract change, update SRS, schemas, generated OpenAPI and fixtures in the same review. Do not ask frontend to infer a changed field from a log. Commit backend code independently of frontend code; shared contract changes get joint review.

## 8. Required verification

Contract/lifecycle tests:
- [ ] Requests and responses validate against the shared schemas, including errors.
- [ ] Duplicate index/retry cannot launch multiple active jobs.
- [ ] Failed preparation and failed indexing retry the correct stage.
- [ ] Restart converts interrupted jobs into visible failures.
- [ ] Unsupported event filter, unready video and invalid time range fail predictably.
- [ ] A search commits complete results before advertising success.
- [ ] Range requests yield correct partial bytes and metadata.

AI/data integration tests:
- [ ] Embeddings have correct dimensions, finite values and persisted clip mapping.
- [ ] Search is restricted to selected videos/time/event filters.
- [ ] Actual source timestamps survive preprocessing and playback.
- [ ] Duplicate windows do not flood the result list.
- [ ] Unrelated query can produce no results.
- [ ] Missing/poor frames cannot produce unsupported certainty.
- [ ] Unavailable Gemini degrades transparently; unavailable retrieval fails explicitly.
- [ ] Model/index versions remain compatible after restart.
- [ ] P1 includes entry, stationary bag, passing person, bag retrieved and occlusion cases.

Use the shared staged-video evaluation described in SRS section 11. Record observed recall@5, false positives and latency; never report planned metrics as measured performance.

## 9. Definition of done and priority cuts

P0 is done only when both developers run upload → preview → optional zone → index → search → evidence → playback on the real pipeline, with mocks disabled, and AC01–AC09 pass. Supply startup commands, pinned dependencies, environment example, model download instructions and known hardware limits in README.

If time is short, defer P1, reference-person search, live feeds and elaborate infrastructure. Preserve working semantic retrieval, honest frame verification, job recovery and playable source evidence. A two-person team should finish this vertical workflow before expanding scope.

## Persistent footage chat — contract 1.1

Gemini chat and Gemini Embedding 2 use the same server-side Google API key. Gemini visual verification uses the same key through GEMINI_VERIFICATION_MODEL (default `gemini-3.5-flash`), and evidence frames go to Google. Persist chats, messages, SearchRequest follow-up context and internal turn tasks. Expose chat creation, detail and asynchronous message endpoints defined in SPEC.md; health advertises actual chat capability. Use bounded execution, one active turn per chat, restart recovery and validated search_video/get_search_results/finish_response tools. Gemini selects actual retrieved result IDs; the backend renders their stored interval, summary and verification reasons rather than publishing freeform model text. Cite stored search/result IDs and preserve evidence limits. Google embedding requests send visual footage content outside the local machine; keep keys and local paths out of the API.

Google model configuration defaults to `gemini-embedding-2` and `gemini-3.5-flash`; override through GEMINI_EMBEDDING_MODEL and GEMINI_CHAT_MODEL. Live model access and acceptance remain unverified until successful API smoke requests and staged-footage evaluation.
