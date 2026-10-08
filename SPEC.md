# Digital Witness — Specification and Integration Contract

Version: 1.1 • Date: 8 October 2026 • Team: one frontend developer and one backend/AI developer

## 1. Purpose and authority

Turn an uploaded CCTV recording into searchable moments. A user types a description, receives ranked clips, and opens the original recording at the relevant time with supporting frame checks.

SPEC.md is the canonical product and API specification for both developers. Digital-Witness-SRS.md is the original companion document; keep its contract content synchronized with this file. Read it before the role-specific plan. The initial delivery is a single-user local demo. All technology choices below are implementation decisions for this plan, not existing implemented features. Contract version is `1.1`; API namespace is `/api/v1`.

Priority: deliver real upload → indexing → search → playback first. Detection/tracking and temporal event inference follow as the second milestone. Do not describe a visually similar match as a proven event.

## 2. Scope and responsibilities

| Capability | Priority | Owner |
|---|---|---|
| Upload MP4, list recordings, view processing state | P0 | Backend API; frontend UI |
| Search clips with Gemini Embedding 2 | P0 | Backend |
| Gemini frame checks for supported visual questions | P0 | Backend |
| Results, evidence panel, original-video playback | P0 | Frontend |
| Draw entrance polygon before indexing | P0 | Frontend; backend validation/storage |
| Error, empty, retry and degraded-verification states | P0 | Both |
| Detect/track people and bags; zone entry and stationary-bag rules | P1 | Backend |
| Explain temporal evidence and display event status | P1 | Both |
| Reference-person identity search, cross-camera re-identification | Deferred | Separate future scope |
| Live RTSP, multiuser login, alerts, mobile app, exports | Deferred | Separate future scope |

P0 supports free-text semantic retrieval. Verification is limited to the declared supported visual checks. P1 introduces `person_entered` and `possible_unattended_bag`; until implemented these are not advertised as supported event filters. Exact identity and “every time this person entered” are outside this MVP.

## 3. User flow

1. Upload an MP4 with a camera label.
2. Wait for preparation, then see a browser-playable preview and metadata.
3. Optionally draw one entrance polygon; coordinates refer to the actual video image, excluding letterboxing. Skip if no zone is needed.
4. Start indexing and display progress until ready or failed.
5. Enter a query, optionally selecting a ready recording, time range or supported event type.
6. Wait for retrieval and verification; display results or a truthful empty state.
7. Select a result to seek the recording to `start_sec`, play through `end_sec`, and inspect evidence.
8. Retry failed preparation/indexing without uploading again. Search failures can be resubmitted as new searches.

## 4. Model roles and evidence rules

Gemini Embedding 2 embeds clips and text for retrieval. Gemini answers predefined single-frame image questions; backend code aggregates frame observations. Neither component alone proves a temporal event. Use original timestamps throughout.

Initial indexing proposal: 8-second windows with a 4-second stride, including the final short window. Persist actual boundaries. Backend may tune window size without changing the API. Use direct visual embeddings; optional template descriptions are separate supporting metadata, not a replacement for visual indexing.

For supported queries, run Gemini on selected readable frames from top candidates, initially up to 3 frames for each of 10 candidates. Record every checked timestamp. For arbitrary queries without a supported check, return `not_checked`; do not fabricate a prompt-specific verification. An internal adapter maps query concepts to an allowlist such as `bag_present` and `person_carrying_bag`.

The visual-check adapter sends one image per request with an allowlisted question and accepts only structured `yes`, `no` or `uncertain` answers. Validate readability first; low quality yields `uncertain`. It returns `probability_yes:null`, because a generated decision does not provide calibrated probabilities or usable class logits. Gemini Embedding 2 uses the Google Gemini API for visual and text embeddings. Gemini chat uses the same server-side GEMINI_API_KEY; Gemini visual checks use the same server-side key through GEMINI_VERIFICATION_MODEL (default `gemini-3.5-flash`). Persist tested API model identifiers, embedding dimensions and preprocessing versions; never expose the key in responses or browser configuration.

Source model cards, reviewed 8 October 2026:
- https://ai.google.dev/gemini-api/docs/image-understanding
- https://ai.google.dev/gemini-api/docs/embeddings

P1 event rules:
- `person_entered`: one track transitions from outside to inside the configured polygon and persists for a configured number of observations.
- `possible_unattended_bag`: tracked bag remains approximately stationary while a previously nearby person moves away for a configured duration. Report a possible event, not ownership or intent. Occlusion and tracking gaps must lower certainty.
- Store rule parameters and algorithm versions with events. Tune durations and pixel/normalized-distance thresholds on the demo footage. Spatial claims come from boxes and polygons, not only language-model answers.

## 5. Architecture and fixed conventions

Frontend: Next.js (App Router) + React + TypeScript; native HTML video; a canvas or SVG polygon overlay. Backend: Python + FastAPI; FFmpeg for probing/transcoding; SQLite metadata; a persistent local vector index; one background worker initially. Backend chooses a tested detector/tracker for P1. CPU mode may be slower; do not promise real-time throughput before measurement.

Interactive upload, polygon editing, polling and playback use Next.js Client Components. Browser calls go directly to FastAPI through a shared API client; FastAPI owns the API and AI pipeline. Frontend configuration uses `NEXT_PUBLIC_API_BASE_URL` and `NEXT_PUBLIC_USE_MOCKS`; these are public build-time values, never secrets.

Suggested repository layout:

```text
frontend/                 # frontend owner
backend/                  # backend owner, including AI adapters
contracts/openapi.json    # backend generated; both review
contracts/fixtures/       # backend authored JSON; frontend consumes
sample-data/README.md     # jointly chosen demo clips and expected moments
README.md                 # shared startup instructions
```

Rules:
- JSON fields are snake_case; all IDs are opaque strings; do not parse IDs.
- UTC RFC3339 for wall-clock metadata; float seconds relative to video start for media.
- Normalized coordinates are floats in `[0,1]`; origin is top-left; x increases right, y down.
- Time intervals are half-open `[start_sec,end_sec)` and satisfy `0 <= start_sec < end_sec <= duration_sec`.
- Nullable fields are explicitly `null`; arrays are always arrays. No `NaN`/infinite JSON values.
- All media URLs returned by backend are absolute HTTP(S) URLs reachable by the browser. Never return filesystem paths.
- Video search filters refer to recording-relative time. A time filter requires exactly one `video_id`.
- Normal JSON success bodies use `{ "data": ... }`; media responses and `/openapi.json` do not use this wrapper.
- Failures use the error envelope in section 8, including FastAPI validation failures.
- No WebSockets in v1. Poll jobs every 2 seconds; stop on terminal state or unmount.
- Default frontend origin `http://localhost:3000`; backend `http://localhost:8000`. Configure an explicit CORS allowlist.
- Local single-user mode has no authentication. Do not publish this mode as a public service.

## 6. Canonical data types

The following TypeScript notation defines wire shapes, not frontend-only models. Every field is required unless marked `?` in request types.

```ts
type VideoStatus = 'preparing' | 'draft' | 'indexing' | 'ready' | 'failed';
type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed';
type JobKind = 'prepare_video' | 'index_video' | 'search';
type EventType = 'person_entered' | 'possible_unattended_bag';
type VerificationStatus = 'supported' | 'uncertain' | 'contradicted' | 'not_checked';
type Point = { x: number; y: number };
type Zone = { zone_id: string; name: string; kind: 'entrance'; polygon: Point[] };
type ApiError = { code: string; message: string; details: Record<string, unknown> };
type Video = {
  video_id: string; filename: string; camera_label: string;
  status: VideoStatus; created_at: string;
  duration_sec: number | null; width: number | null; height: number | null;
  playback_url: string | null; thumbnail_url: string | null;
  zones: Zone[]; active_job_id: string | null; error: ApiError | null;
};
type Job = {
  job_id: string; kind: JobKind; resource_id: string; status: JobStatus;
  stage: 'queued' | 'preparing' | 'embedding' | 'detecting' | 'retrieving' |
    'verifying' | 'finalizing' | 'complete' | 'failed';
  progress_pct: number; created_at: string; updated_at: string;
  error: ApiError | null;
};
type FrameCheck = {
  check_id: string; question: string;
  answer: 'yes' | 'no' | 'uncertain'; probability_yes: number | null;
};
type EvidenceFrame = {
  timestamp_sec: number; image_url: string;
  quality: 'usable' | 'poor'; checks: FrameCheck[];
};
type SearchResult = {
  result_id: string; video_id: string; camera_label: string;
  start_sec: number; end_sec: number; thumbnail_url: string;
  playback_url: string; summary: string;
  event_type: EventType | null; zone_id: string | null;
  retrieval_score: number;
  verification: {
    status: VerificationStatus; reason: string;
    basis: 'frame_checks' | 'temporal_rule' | 'none';
  };
  evidence: EvidenceFrame[];
};
type SearchRequest = {
  query: string; video_ids: string[]; limit?: number;
  time_range?: { start_sec: number; end_sec: number };
  event_types?: EventType[];
};
type Search = {
  search_id: string; job_id: string; status: JobStatus;
  query: string; video_ids: string[]; created_at: string;
  warnings: { code: string; message: string }[];
  results: SearchResult[]; error: ApiError | null;
};
```

`retrieval_score` is cosine similarity in `[-1,1]`, not an accuracy percentage. Probability values are in `[0,1]` but do not imply calibrated CCTV accuracy. `supported` means the declared checks support their narrow claim; show `basis` and `reason`. A bag-presence check cannot label abandonment supported. Template `summary` must describe observed evidence without implying unverified identity or intent.

## 7. HTTP API contract

| Method and route | Request | Success response |
|---|---|---|
| GET `/api/v1/health` | None | 200 `{data:{status:"ok",contract_version:"1.1",mode:"live",capabilities:{semantic_search:true,chat:true,frame_verification:true,temporal_events:false},supported_event_types:[]}}` |
| POST `/api/v1/videos` | Multipart `file` and `camera_label` | 202 `{data:{video:Video,job:Job}}` |
| GET `/api/v1/videos?limit=20&offset=0` | limit 1–100; offset >=0 | 200 `{data:{items:Video[],total:number,limit:number,offset:number}}` |
| GET `/api/v1/videos/{video_id}` | None | 200 `{data:Video}` |
| PUT `/api/v1/videos/{video_id}/zones` | `{zones:[{name,kind:"entrance",polygon:Point[]}]}` | 200 `{data:Video}` |
| POST `/api/v1/videos/{video_id}/index` | Empty JSON `{}` | 202 `{data:{video:Video,job:Job}}` |
| POST `/api/v1/videos/{video_id}/retry` | Empty JSON `{}` | 202 `{data:{video:Video,job:Job}}` |
| GET `/api/v1/jobs/{job_id}` | None | 200 `{data:Job}` |
| POST `/api/v1/searches` | `SearchRequest` | 202 `{data:{search_id:string,job:Job}}` |
| GET `/api/v1/searches/{search_id}` | None | 200 `{data:Search}` |
| GET `/api/v1/media/{media_id}` | Optional HTTP Range | 200 or 206 media bytes |

Health uses `mode:"mock"` for an explicitly configured mock server. Unavailable model adapters are advertised as false capabilities, not silently mocked. If semantic search cannot run, search creation returns 503. If frame verification becomes unavailable, search may succeed with warnings and `not_checked` results. P1 advertises `temporal_events:true` and the exact enabled event types.

Upload rules: one file, maximum 500 MiB, maximum 30-minute duration; camera label 1–80 trimmed characters. Accept MP4 container; validate actual content. File size violations return 413 synchronously. Decoder/duration problems found during preparation fail the preparation job. Backend creates a browser-compatible H.264 MP4 derivative when necessary, preserving the time axis. Empty or unreadable media fails clearly.

Zone rules: at most one entrance; 3–12 non-repeated vertices; non-zero-area simple polygon; do not repeat first vertex to close. Empty `zones` clears the zone. Backend creates `zone_id`. Zone replacement is allowed only in `draft`, or `failed` when preparation already succeeded. Otherwise return 409. Changing zones after indexing is deferred; this prevents stale zone/event associations.

Search rules: query 1–500 trimmed characters; `video_ids` contains 1–20 distinct ready video IDs; `limit` defaults to 10, range 1–50. Omitted/empty `event_types` means no event filter. A requested unsupported event type returns 422, not silently ignored. Filter by time overlap, retain actual clip boundaries; do not invent clipped event evidence. Apply filters before final ranking/limit. Order by similarity descending, then video_id and start_sec. Merge overlapping duplicate windows within a video for the same candidate event before taking limit; distinct nearby events must remain separate.

No partial search results in v1: `results:[]` until succeeded. A succeeded search may legitimately contain zero results. Apply a backend-configured, validation-derived relevance threshold rather than always presenting the nearest clip as a match. Backend owns ranking and merging; frontend preserves returned order. Empty result is not proof that an event never occurred.

### Upload → index → search example

```http
POST /api/v1/videos
Content-Type: multipart/form-data; boundary=<browser-generated>
file=<recording.mp4>
camera_label=Entrance Camera
```

Use returned `job.job_id` to poll. Once the video is `draft`, optionally save a zone:

```json
{"zones":[{"name":"Main entrance","kind":"entrance","polygon":[{"x":0.1,"y":0.2},{"x":0.4,"y":0.2},{"x":0.4,"y":0.9},{"x":0.1,"y":0.9}]}]}
```

Start indexing, then wait for `ready`. Search:

```json
{"query":"person carrying a bag near the entrance","video_ids":["vid_demo_01"],"limit":10,"time_range":{"start_sec":0,"end_sec":120}}
```

The 202 response contains a new search ID and job. On job success, GET the search. Example succeeded `data` value (illustrative, not measured output):

```json
{
  "search_id":"search_demo_01","job_id":"job_search_01","status":"succeeded",
  "query":"person carrying a bag near the entrance","video_ids":["vid_demo_01"],
  "created_at":"2026-10-08T04:30:00Z","warnings":[],"error":null,
  "results":[{
    "result_id":"result_01","video_id":"vid_demo_01","camera_label":"Entrance Camera",
    "start_sec":32.0,"end_sec":40.0,
    "thumbnail_url":"http://localhost:8000/api/v1/media/thumb_01",
    "playback_url":"http://localhost:8000/api/v1/media/video_01",
    "summary":"Candidate clip: a person appears to carry a bag. Entrance proximity has not been verified.",
    "event_type":null,"zone_id":null,"retrieval_score":0.72,
    "verification":{"status":"supported","basis":"frame_checks","reason":"Supports bag carrying in a sampled frame only; entrance proximity and temporal actions are unverified."},
    "evidence":[{"timestamp_sec":35.0,"image_url":"http://localhost:8000/api/v1/media/frame_01",
      "quality":"usable","checks":[{"check_id":"person_carrying_bag","question":"Is a person visibly carrying a bag?","answer":"yes","probability_yes":null}]}]
  }]
}
```

The frontend labels this “Frame check supported,” not “Event confirmed.”

### Persistent footage chat (contract 1.1)

Contract 1.1 adds persistent footage chat; existing `/api/v1` routes remain unchanged.

```ts
type ChatMessage = {
  message_id: string; role: 'user' | 'assistant'; text: string;
  created_at: string; search_ids: string[]; result_ids: string[];
};
type Chat = {
  chat_id: string; video_ids: string[]; created_at: string; updated_at: string;
  status: 'idle' | 'running' | 'failed'; active_turn_id: string | null;
  context: SearchRequest | null; messages: ChatMessage[]; error: ApiError | null;
};
type ChatCreateRequest = { video_ids: string[] };
type ChatMessageRequest = { message: string };
type ChatTurnAccepted = { chat_id: string; turn_id: string };
```

| Method and route | Request | Success response |
|---|---|---|
| POST `/api/v1/chats` | `ChatCreateRequest` | 201 `{data:Chat}` |
| GET `/api/v1/chats/{chat_id}` | None | 200 `{data:Chat}` |
| POST `/api/v1/chats/{chat_id}/messages` | `ChatMessageRequest` | 202 `{data:ChatTurnAccepted}` |

Chat creation requires 1–20 distinct ready video IDs. Messages contain 1–2000 trimmed characters. Unknown chat IDs return 404 `CHAT_NOT_FOUND`; unavailable Gemini chat returns 503 `MODEL_UNAVAILABLE`. Health adds the required boolean `capabilities.chat` and reports contract version `1.1`.

Chat preserves messages and the most recent validated SearchRequest context across refresh and restart. Follow-ups can reuse recording and time filters. A single bounded chat worker processes persisted internal tasks; each chat permits one active turn. These internal tasks do not extend public JobKind. Conflicting turns return 409 and a full queue returns 429 `QUEUE_FULL` with Retry-After. Interrupted turns terminate with an actionable error after restart. Poll chat detail every two seconds while running, stopping on terminal status or unmount.

Gemini may invoke only backend-authorized `search_video`, `get_search_results` and `finish_response` tools. The backend validates selected video IDs and all search filters before executing tools. Gemini finishes by selecting unique result IDs already read from complete search results through `finish_response`; the backend renders stored summaries, source intervals, verification status, basis and reasons. Assistant messages retain cited search/result IDs. Freeform model text cannot publish a final explanation. Empty-result and processing-failure replies require a corresponding completed empty search or actual tool failure. Missing-input replies use fixed query, recording or time-range prompts. Summaries must distinguish semantic candidates, narrow frame checks and temporal rules; no identity, ownership, intent or event claim exceeds cited source evidence. A no-match answer does not prove an event never happened. Arbitrary client paths or model-proposed tools cannot grant access to other recordings.

All three Google adapters share GEMINI_API_KEY exclusively on the server. The configured defaults are `gemini-embedding-2` and `gemini-3.5-flash`, overridden through `GEMINI_EMBEDDING_MODEL` and `GEMINI_CHAT_MODEL`. Capability requires successful adapter smoke tests; these identifiers do not constitute verified live model access or immutable model revisions. Clip/frame embedding requests send selected footage content to Google; chat requests send conversation and tool-result evidence. Gemini visual verification sends evidence frames to Google and provides allowlisted checks; GEMINI_VERIFICATION_MODEL defaults to `gemini-3.5-flash`. Missing credentials or unavailable Google APIs never fall back to canned answers. Joint frontend integration and real-footage acceptance remain required.

## 8. Errors, lifecycle and recovery

```json
{"error":{"code":"VIDEO_NOT_READY","message":"Wait for indexing to finish before searching.","details":{"video_id":"vid_demo_01"}},"request_id":"req_example"}
```

| HTTP | Codes | Frontend behavior |
|---|---|---|
| 404 | `VIDEO_NOT_FOUND`, `JOB_NOT_FOUND`, `SEARCH_NOT_FOUND`, `MEDIA_NOT_FOUND`, `CHAT_NOT_FOUND` | Explain missing resource; return to list |
| 409 | `VIDEO_NOT_READY`, `INVALID_STATE`, `JOB_ALREADY_RUNNING` | Refresh resource; do not blindly resubmit |
| 413 | `FILE_TOO_LARGE` | Show 500 MiB limit |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Request MP4 |
| 422 | `VALIDATION_ERROR`, `INVALID_ZONE`, `UNSUPPORTED_EVENT_TYPE` | Show actionable field errors in details |
| 429 | `QUEUE_FULL` | Respect `Retry-After` seconds; allow retry |
| 503 | `MODEL_UNAVAILABLE` | Explain unavailable processing; keep existing results |
| 500 | `INTERNAL_ERROR` | Show request ID and retry action |

Job errors use `ApiError` with codes such as `MEDIA_DECODE_FAILED`, `DURATION_EXCEEDED`, `INDEXING_FAILED`, `SEARCH_FAILED`, `WORKER_INTERRUPTED`. Never expose stack traces or host paths.

Video lifecycle: upload creates `preparing`; successful preparation → `draft`; index request → `indexing`; successful atomic index commit → `ready`; preparation/index failure → `failed`. `active_job_id` is cleared on terminal completion; failed video retains `error`. Job lifecycle is queued → running → succeeded/failed. Percentage never decreases and is 100 only on success; UI treats it as estimated work, not elapsed time.

`retry` is valid only for failed videos and repeats the failed stage: preparation or indexing. It creates a new job, clears video error, cleans/replaces partial output and avoids duplicate vectors. Double index or retry requests while active return 409. Workers persist job state; restart marks interrupted active jobs failed so polling does not hang forever. Search status mirrors its job, with results committed before success becomes visible.

Media service must support browser seeking with `Accept-Ranges: bytes`, valid `Content-Type`, `Content-Length`, 206/`Content-Range`, and 416 for unsatisfiable ranges. Serve only ID-mapped media, never arbitrary caller-supplied paths.

## 9. Storage and nonfunctional requirements

Persist videos, zones, jobs, searches, clips, evidence and index metadata. Every vector maps to a video/clip ID and model revision. Persist media separately from SQLite; do not store video blobs in JSON. Bound the worker queue, initially 20 queued jobs and one running job. Model calls run off the HTTP request thread. Search latency and indexing speed are measured on the team's hardware and reported, not guessed.

The UI remains usable during processing. Polling survives page refresh by reloading video state and storing active search ID. Show no invented progress. On network failure, retain the last known state and offer reconnect. Index writes become visible atomically; never search a partially indexed video. Keep model/API credentials server-side. Mock mode must be visibly labelled and unavailable by default in the live demo configuration.

## 10. Integration procedure and change control

1. Both developers agree to this v1.1 contract before coding.
2. Backend publishes Pydantic schemas, `/openapi.json`, and complete fixtures for all states in `contracts/`.
3. Frontend generates/imports types from OpenAPI and wraps calls in a single API module. Components never hardcode service URLs.
4. Both use the same fixtures and IDs. Fixtures include working local test media URLs, not only placeholder URLs from this document.
5. Changes to routes, field types, nullability or enum values require a small contract PR reviewed by both developers before implementation. Update SRS, OpenAPI and fixtures together.
6. Merge early: one fixture-based integration, then a real upload/index/search pass, then P1 work. Do not wait until the end to connect.
7. Backend owns `backend/` and generated OpenAPI; frontend owns `frontend/`. Shared files change in separate small commits.

## 11. Acceptance criteria and joint test set

- AC01: Valid video uploads, prepares, previews, indexes and reaches ready without blocking HTTP requests.
- AC02: Polygon survives reload and aligns with the image after viewport resize/letterboxing.
- AC03: Query returns playable timestamped candidates; selecting a result seeks to its start and pauses at its end, with an option to continue.
- AC04: Evidence frames/checks and verification scope are visible; scores never appear as “accuracy %.”
- AC05: An unrelated query can return zero results; no-match UI differs from a server error.
- AC06: Poor-frame or unavailable Gemini verification returns uncertain/not_checked with explanation, never invented certainty.
- AC07: Failed preparation/indexing can retry without duplicate clips/vectors. Restarted worker jobs terminate visibly.
- AC08: Frontend runs against fixtures and the real API without component rewrites; all response shapes pass schema validation.
- AC09: Media Range requests enable seeking on a fresh browser session, not only after full download.
- AC10 (P1): Entry and possible unattended-bag results expose temporal basis; brief passing, occlusion and a person remaining beside a bag are negative cases.

Joint benchmark: record 3–5 short consenting/staged videos with bags, empty scenes, entry, carrying, leaving and retrieval. Label expected intervals for at least 10 queries, including unrelated and ambiguous queries. Report retrieval recall@5 using interval overlap, false positives, verification outcomes and measured latency. Keep development and final evaluation examples separate where practical. This is evaluation work to be performed; no accuracy claim is made by this SRS.

Definition of done for P0: AC01–AC09 pass on the live pipeline, no critical contract mismatch remains, both developers can start the stack from README, and known limitations are documented. P1 is separately accepted against AC10.
