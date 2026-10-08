# Digital Witness — System and Interface Design

Version: 1.1 • Date: 8 October 2026 • Status: implementation blueprint

This document describes the design to build, not an implemented application. [SPEC.md](SPEC.md) owns the exact API and acceptance requirements. [AGENTS.md](AGENTS.md) assigns responsibility to both teammates.

## Product experience

A single-user local browser application turns uploaded CCTV recordings into searchable candidate moments. Every candidate opens the source recording at its actual timestamp and exposes the evidence behind its label.

The main workspace has a recording library, search controls, ranked results and a selected-result player with evidence. Start with a functional desktop layout; on narrow screens stack panels in the same reading order. Use restrained colors, readable typography and consistent spacing. Reserve color for statuses and actions, and always pair it with text.

## Screens and interactions

| Area | Required behavior |
|---|---|
| Recording library | Upload MP4 and camera label; show duration, processing state, error and available action; paginate recordings |
| Preparation and zone setup | Show playable preview after preparation; optionally draw one entrance polygon; save before indexing or explicitly skip |
| Processing | Show backend stage and estimated percentage; keep the workspace usable; expose retry for failed recordings |
| Search | Require query and ready recordings; optionally filter time for exactly one recording; expose only health-advertised event filters |
| Results | Preserve backend order; show thumbnail, camera, interval, summary and verification label; distinguish empty results from errors |
| Player and evidence | Seek after metadata loads; pause at interval end unless Continue recording is enabled; evidence frames seek to their source timestamp |

Upload transfer and backend preparation are different states. Do not invent timed progress. Retain unsaved polygon edits after a failed save and prevent indexing until edits are saved or discarded. A ready recording's zone is read-only in v1.

Compute polygon coordinates against the actual displayed image rectangle, excluding letterboxing. Store floats in [0,1] and reproject them on resize. Support adding points, undoing the last point, clearing and saving; surface server validation errors.

Give every form control a visible label and keyboard focus state. Provide usable keyboard controls for the zone editor, such as focused point inputs. Status and error messages must be readable without color. Loading, unavailable, empty and failed states each explain the next available action.

## Evidence presentation

| Verification | User label |
|---|---|
| supported with frame_checks | Frame check supported |
| supported with temporal_rule | Temporal rule supported |
| uncertain | Needs review |
| contradicted | Check did not support this candidate |
| not_checked | Not checked |

Always show basis and reason alongside evidence. A bag-carrying check supports that visible attribute only; it does not establish entrance proximity or abandonment. Keep cosine similarity in optional details as a raw score. Search-level warnings remain visible when verification degrades. No results means no matches passed retrieval criteria, not proof that an event never happened.

## System boundaries

```text
Next.js (App Router) + React + TypeScript browser
    | /api/v1 JSON and multipart upload
    v
FastAPI routes and Pydantic schemas
    | orchestration and persistent job queue
    v
One background worker
    |-- FFmpeg/ffprobe: validate, prepare media, sample original timestamps
    |-- Embedding adapter: clip/text retrieval vectors
    |-- Verification adapter: allowlisted single-frame checks
    |-- P1 tracking and temporal rules
    v
SQLite metadata + media files + persistent local vector index

Browser video player <-- ID-mapped HTTP media service with Range support
```

Next.js App Router supplies pages and layouts. Interactive upload, polygon editing, polling and video controls use Client Components; browser APIs run in effects or event handlers. Browser calls go directly to FastAPI. Fetch changing job/search state without caching.

The frontend API module owns base URLs, envelopes and error parsing. UI components consume that module and generated/imported contract types. Fixtures use the same interface as live responses and simulate terminal lifecycle transitions.

Backend routes validate and enqueue work promptly. Services coordinate persistence and lifecycle. Worker operations run off the HTTP request thread; the initial queue holds at most 20 queued jobs with one running job. Adapters isolate model runtime details from API schemas. Storage maps opaque public media IDs to internal files and never accepts arbitrary client paths.

## Data and processing

Preparation creates a browser-compatible derivative when needed while preserving the original time axis. Successful preparation produces draft; explicit indexing produces indexing then ready. Failed attempts retain actionable errors and retry only the failed stage.

The initial retrieval proposal uses 8-second windows and a 4-second stride, preserving final partial windows and actual boundaries. Every vector records its video, clip and model revision. Publish the index atomically so partially indexed recordings cannot be searched.

Search validates ready recordings and filters, embeds the query, retrieves candidates, merges overlapping duplicates for the same event, applies the configured relevance threshold and returns ordered results. Publish complete results before exposing success; no partial result stream in v1.

Verification uses allowlisted concepts such as bag_present and person_carrying_bag. Check sampled-frame readability before inference. Unsupported concepts return not_checked; poor images yield uncertainty. If verification is unavailable, retain semantic results with warnings. If retrieval is unavailable, return the specified service error.

The existing plan proposes Gemini Embedding 2 and Gemini visual verification. Validate actual model support, revisions and runtime requirements during implementation; this design makes no measured performance claim. P1 adds a separately tested detector/tracker and geometric temporal rules for person_entered and possible_unattended_bag.

## Persistence and recovery

Persist recordings, zones, jobs, clip/index metadata, searches and evidence. Keep media files separate from SQLite. Associate outputs with processing attempts so retries clean partial artifacts without deleting published data. Mark interrupted active jobs failed on worker restart.

The browser restores recording state and active search ID after refresh. Stop polling on completion or unmount, retain last known state on network failure, and respect Retry-After. Prevent stale query responses from replacing a newer search. Avoid automatic mutation retries after ambiguous network timeouts.

## Repository and configuration

| Path | Purpose |
|---|---|
| frontend/ | Browser application and UI checks |
| backend/ | API, worker, adapters, storage and backend checks |
| contracts/openapi.json | Backend-generated shared API description |
| contracts/fixtures/ | Complete canonical request/response examples |
| sample-data/README.md | Consenting/staged demo footage instructions and expected moments |
| README.md | Verified setup, startup, evaluation and hardware limitations |

These are planned directories, not an assertion that code exists. Frontend defaults to localhost:3000 and backend to localhost:8000. Configure an explicit CORS origin allowlist and reachable absolute media URLs. Use NEXT_PUBLIC_API_BASE_URL and NEXT_PUBLIC_USE_MOCKS in frontend/.env.local, with safe placeholders in .env.example; public values are embedded at build time. Browser configuration is public; keep model credentials in backend configuration. Local unauthenticated mode is intended for the local demo.

## Integration gates

Connect fixture screens first, real preparation and media second, and real indexing/search/evidence third. Both teammates review contract changes before implementation. Keep SPEC.md, the original SRS, schemas, generated OpenAPI and fixtures synchronized.

P0 completion requires AC01–AC09 from SPEC.md on real footage with mocks disabled and startup instructions that both teammates can follow. Benchmark consenting/staged footage with expected intervals, unrelated queries and poor-frame cases; report observed recall@5, false positives and latency. P1 is accepted separately against AC10.

## Persistent footage chat — contract 1.1

Gemini chat and Gemini Embedding 2 use the same server-side Google API key. Gemini visual verification uses the same key through GEMINI_VERIFICATION_MODEL (default `gemini-3.5-flash`), and evidence frames go to Google. Persist chats, messages, SearchRequest follow-up context and internal turn tasks. Expose chat creation, detail and asynchronous message endpoints defined in SPEC.md; health advertises actual chat capability. Use bounded execution, one active turn per chat, restart recovery and validated search_video/get_search_results/inspect_frames/finish_response tools. Gemini inspects timestamped source images for footage questions; the backend validates frame citations and attaches readable timestamps. Narrow frame checks remain separate from general visual answers. Cite stored search/result IDs and preserve evidence limits. Google embedding requests send visual footage content outside the local machine; keep keys and local paths out of the API.

Google model configuration defaults to `gemini-embedding-2` and `gemini-3.5-flash`; override through GEMINI_EMBEDDING_MODEL and GEMINI_CHAT_MODEL. Live model access and acceptance remain unverified until successful API smoke requests and staged-footage evaluation.
