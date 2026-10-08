# Digital Witness — Frontend Developer Plan

Owner: Person 1 • Contract: v1.0 • Date: 8 October 2026

## 1. Your goal

Build a complete browser experience for uploading CCTV footage, marking an entrance, monitoring processing, searching moments, and viewing evidence. The backend developer owns all model inference, indexing, detection and ranking.

Read [Digital-Witness-SRS.md](Digital-Witness-SRS.md) first. Its section 6 types and section 7 endpoints are authoritative. Coordinate with [Digital-Witness-Backend-Plan.md](Digital-Witness-Backend-Plan.md). Do not independently rename fields or invent endpoint shapes.

## 2. Technology and ownership

Use Next.js (App Router) + React + TypeScript, a native HTML video player, and SVG/canvas for zone editing. Keep the UI library simple and familiar. Own `frontend/`; keep service access in one API module. Backend exports OpenAPI and fixtures in `contracts/`.

Suggested structure:

```text
frontend/src/
  app/layout.tsx            # shared application shell
  app/page.tsx              # recording/search workspace entry
  app/globals.css           # global styles
  api/client.ts             # base URL, envelopes, errors, requests
  api/types.ts              # generated from approved OpenAPI
  api/mock.ts               # same client interface; dev-only fixtures
  features/videos/          # upload, list, details, status
  features/zones/           # polygon editing and validation
  features/search/          # query, filters, polling, results
  features/player/          # media playback and evidence
  components/               # common progress/error/empty UI
```

Configuration: `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1`; `NEXT_PUBLIC_USE_MOCKS=false`. Build request URLs from this base. Use returned media URLs unchanged; do not prefix them a second time. Browser environment variables are public: no model keys or server secrets belong here.

### Next.js boundaries and development

Keep App Router layouts/pages as Server Components where appropriate. Mark interactive entry components with `'use client'`: uploads, polygon editing, polling/search state, player controls and evidence interactions. Access `window`, `sessionStorage`, media refs and browser APIs in effects or event handlers so initial rendering does not fail.

Browser requests go directly to FastAPI through the shared API client, including multipart uploads and media playback. FastAPI continues to own `/api/v1`, persistence, jobs and AI inference. Use client polling for changing job/search state; request fresh data with `cache: 'no-store'`. Keep live/mock selection identical across initial rendering and hydration.

Store local environment values in `frontend/.env.local` and publish safe placeholders in `.env.example`. Read public variables explicitly as `process.env.NEXT_PUBLIC_API_BASE_URL` and `process.env.NEXT_PUBLIC_USE_MOCKS === 'true'`. Next.js embeds public values at build time, so rebuild when changing deployed configuration. Never expose secrets with the `NEXT_PUBLIC_` prefix.

Once scaffolded, document package scripts for `next dev`, `next build` and `next start`; use port 3000 locally and configure backend CORS for `http://localhost:3000`. Verify both production build and interactive behavior before handoff.

References: [Server and Client Components](https://nextjs.org/docs/app/getting-started/server-and-client-components), [Environment Variables](https://nextjs.org/docs/app/guides/environment-variables).

## 3. Screens and behavior

### A. Recording library

Show upload control, camera label, list of recordings, duration, status and relevant action. Backend pagination is `limit` and `offset`, with `total`. Status actions:

| Video state | UI action |
|---|---|
| preparing | Show preparation progress; disable indexing/search |
| draft | Open preview, edit entrance zone, start indexing |
| indexing | Show current stage and estimated progress |
| ready | Enable search and playback; zone is read-only |
| failed | Show error and Retry action |

Client prechecks file size and MP4 selection, but server validation is authoritative. Use `FormData` keys `file` and `camera_label`; do not manually set multipart Content-Type because the browser supplies the boundary. Distinguish upload bytes sent from server processing progress. If byte progress is unavailable, use an indeterminate upload indicator.

### B. Preview and entrance editor

Display prepared preview. Let the user add 3–12 polygon vertices, undo the last point, clear, and save. One entrance maximum. Show a Skip action; search without a zone is valid. Save via PUT zones, then use the returned Video including server-generated zone_id.

Map pointer positions through the displayed video's image rectangle, excluding letterboxing: `(pointer_x-image_left)/image_width` and `(pointer_y-image_top)/image_height`. Reject clicks outside this rectangle. Store normalized points. Recompute rendered positions on resize. Do not save CSS pixel coordinates.

Require successful zone save before enabling Start indexing when edits are pending. Lock editor once indexing begins. No post-index zone editing in v1. Show failed save without discarding unsaved points.

### C. Search workspace

Controls: query, selected ready recordings, optional start/end time for a single recording, optional enabled event types, Search button. Require at least one ready recording. Defaults: limit 10 and no event filter. Parse `mm:ss` display input into numeric seconds; never send formatted time strings.

Fetch health capabilities to decide which event controls to expose. For P0, semantic search and frame verification are visible; temporal event filters are hidden. Disable filters unavailable on the server.

POST searches, keep returned search_id and job_id, poll job, and GET search on completion. On failed job, retrieve/display the search error. Ignore stale responses when a newer search was submitted. Aborting client polling does not cancel server work; do not claim otherwise. Store active search ID in session storage so refresh can recover it.

### D. Results and evidence

Each result card shows thumbnail, camera label, start/end time, summary and verification label. Preserve backend result order. Show raw similarity only in optional details, never as percent accuracy.

Map verification labels carefully:
- supported + frame_checks → “Frame check supported.”
- supported + temporal_rule → “Temporal rule supported.”
- uncertain → “Needs review.”
- contradicted → “Check did not support this candidate.”
- not_checked → “Not checked.”

Always expose reason and evidence; a frame label does not confirm the entire query. Show warnings at search level. Empty successful result shows “No matching moments found”; failed search shows an error with retry.

Clicking a card loads playback_url, waits for loadedmetadata, seeks to start_sec and handles rejected play promises with a visible Play control. On timeupdate, pause at end_sec unless “Continue recording” is selected. Evidence thumbnails seek to timestamp_sec. All timestamps refer to the same original recording timeline. No browser-generated clip extraction is required.

## 4. Ordered implementation tasks

### F1 — Contract and working skeleton

- Read SRS with backend developer; settle any ambiguity before coding.
- Create Next.js App Router app, layout, client component boundaries, API wrapper and structured ApiError handling.
- Import/generate types from backend OpenAPI; keep fixtures typed.
- Implement live/mock switch with a persistent visible mock badge.
- Build status and error components before feature-specific screens.

Deliverable: app can load fixture videos and show all lifecycle states.

### F2 — Upload, preview and indexing

- Connect upload and video listing; support pagination.
- Poll preparation job; refresh Video at terminal state.
- Implement normalized entrance polygon and PUT save.
- Connect POST index and POST retry; disable duplicate clicks.
- Implement reload recovery via GET Video and active_job_id.

Deliverable: real video reaches ready from UI, before adding search polish.

### F3 — Search and playback

- Add form validation and health-driven event filters.
- Submit async search and show queued/retrieving/verifying stages.
- Render results, evidence, warnings and empty state.
- Implement original-video seeking and interval playback.
- Handle rapid consecutive searches without showing stale results.

Deliverable: real query opens real footage at the matching interval.

### F4 — Integration and completion

- Replace fixture URLs with backend-returned reachable media URLs in live mode.
- Verify CORS from the actual development origin.
- Test seeking before video fully downloads.
- Check resizing, keyboard navigation, field labels and readable status text.
- Run the joint acceptance checklist and update README startup steps.

Deliverable: AC01–AC09 frontend portions pass; any remaining limitations documented.

## 5. Backend handoffs you require

| Needed from backend | When | Why |
|---|---|---|
| Approved OpenAPI + complete JSON fixtures | F1 | Build without waiting for models |
| Health, upload, videos, jobs, media routes | F2 | Integrate real preparation/playback early |
| Zone save, index and retry | F2 | Finish ingest workflow |
| Search job and result routes | F3 | Complete core demo |
| Real evidence images and explanations | F3 | Show verified scope accurately |
| Capability update for P1 | After P0 passes | Enable temporal filters without API redesign |

Fixtures required: preparing, draft, indexing, ready, failed videos; queued/running/succeeded/failed jobs; populated/empty/degraded/failed searches; representative 409/422/503 envelopes. Backend owns canonical fixture values. Your mocks simulate lifecycle transitions rather than freezing permanently in running.

## 6. Integration rules

- No direct calls from UI components to Hugging Face or model services.
- No client-side ranking, probability thresholds or event inference.
- Do not retry POST uploads/index/search automatically after an ambiguous network timeout; first inspect available resource state. Explicit user retry may create a new search or upload.
- Stop timers on terminal state and unmount. Back off on network failure; respect Retry-After for 429.
- All API failures use one parser. A missing optional capability is not a frontend crash.
- Use contract PRs for required new data. Never quietly depend on an undocumented field.
- Keep frontend commits separate from backend files. Review shared contract changes together.

## 7. Your test checklist

- [ ] Upload valid MP4; reject oversized selection; show decoder failure returned later by job.
- [ ] Correct progress stage during preparation and indexing; no fake percentage timer.
- [ ] Polygon alignment remains correct with letterboxing and resizing.
- [ ] Save failure retains drawn polygon; no indexing with unsaved changes.
- [ ] Query validates nonempty text, selected video, time range and event capability.
- [ ] Populated, empty, uncertain, not_checked, contradicted and failed results render.
- [ ] Fresh media URL can seek before full file download.
- [ ] Switching result/query cannot display stale frames or old results as current.
- [ ] Page reload recovers processing state and active search.
- [ ] Real backend works with mocks disabled; no fixture imports reach live responses.

## 8. Suggested two-person schedule

Use these as work blocks, not a promise that model integration fits a fixed hackathon duration.

| Block | Frontend focus | Joint checkpoint |
|---|---|---|
| 1 | Contract, skeleton, fixtures | Agree request/response samples |
| 2 | Upload, list, player, zone editor | Real video previews |
| 3 | Index state, search results UI | Real indexing and first search |
| 4 | Evidence and error handling | End-to-end P0 acceptance |
| 5, if available | P1 labels/filters and UI polish | Temporal event demonstration |

If time is short, keep single-recording search and a plain functional UI. Never cut live playback, honest verification labels or integration testing to add cosmetic features.
