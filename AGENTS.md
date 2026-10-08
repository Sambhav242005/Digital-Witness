# Digital Witness — Team and Agent Instructions

Applies to the entire repository and to assistants working for either teammate.

## Read before working

1. Read [SPEC.md](SPEC.md) for scope, wire types, API routes, lifecycle, and acceptance criteria.
2. Read [DESIGN.md](DESIGN.md) for architecture and interface behavior.
3. Read the plan for your assigned role: [frontend](Digital-Witness-Frontend-Plan.md) or [backend and AI](Digital-Witness-Backend-Plan.md).

SPEC.md controls product and integration requirements. Role plans describe implementation order. If documents disagree, flag the mismatch and synchronize them before changing the contract. Keep Digital-Witness-SRS.md consistent with SPEC.md when changing requirements.

The session references RTK.md, but that file was absent when these instructions were created. If it is added, read it and follow its applicable instructions. Do not invent missing RTK rules.

## Two-person ownership

Roles are independent of names; either teammate can take either role by agreement.

| Role | Owns | Gives the other teammate |
|---|---|---|
| Frontend developer | frontend/, browser API client, upload and zone UI, search, evidence, playback | Working screens, reproducible UI issues, frontend acceptance results |
| Backend and AI developer | backend/, model adapters, storage, worker, media delivery, generated contracts/openapi.json and fixtures | Schemas, complete fixtures, live endpoints, model and hardware limitations |
| Both | SPEC.md, DESIGN.md, SRS, README, demo footage and acceptance | Reviewed contract changes and an end-to-end working demo |

Work in your owned directories. Coordinate changes to the other role's files. Put shared contract changes in a focused commit or PR that both teammates review. Never overwrite a teammate's uncommitted work.

## Delivery order

1. Establish the v1.0 contract, backend schemas, fixtures and frontend skeleton.
2. Integrate real upload, preparation, preview, optional entrance zone, indexing and retry.
3. Integrate real semantic search, supported frame checks, evidence and source playback.
4. Pass AC01–AC09 with mocks disabled and document startup and measured limitations.
5. Only then implement P1 tracking and temporal rules, accepted against AC10.

Live streams, authentication, cross-camera identity, alerts, exports and mobile applications are deferred. Avoid expanding scope while the core workflow remains incomplete.

## Shared implementation rules

- Build the frontend with Next.js App Router, React and TypeScript. Use Client Components for upload, zones, polling and playback; keep API and AI work in FastAPI. Default frontend origin is http://localhost:3000.
- Preserve /api/v1 routes, snake_case fields, opaque IDs, explicit nulls and envelopes from SPEC.md.
- Use recording-relative seconds, half-open intervals and normalized image coordinates. Preserve the source time axis through media processing.
- Keep ranking, relevance thresholds, model calls and event inference on the backend. The frontend preserves result order.
- Report actual capabilities. Mock mode is explicit and visibly labelled; live mode never silently returns canned matches.
- Separate cosine similarity, frame-check probability and temporal evidence. Never show a similarity score as accuracy or claim identity, ownership or intent from these models.
- Poll jobs every two seconds; stop on terminal state or unmount. Recover persisted state after refresh and interrupted work after restart.
- Validate uploads, polygons and search filters on the server. Serve only ID-mapped media with correct byte-range behavior.
- Keep secrets server-side. Exclude credentials, private footage, model weights, databases, vectors and generated runtime media from commits.
- Pin model revisions and package versions after actual compatibility checks. Consult official model documentation when implementing; planned capabilities are not verified results.

## Verification and handoff

Run checks relevant to the change using the project's documented commands once the application exists. Do not claim tests ran when only documentation exists.

Frontend checks cover lifecycle states, letterboxed/resized polygons, stale-search protection, reload recovery, keyboard operation, evidence labels and fresh-video seeking. Backend checks cover contract validation, state transitions, retry cleanup, worker restart, filters, atomic result publication and Range/206/416 responses. Both run the staged-video acceptance workflow defined in SPEC.md.

Include changed behavior, validation performed, known limitations and the next handoff in each implementation PR. Update specification, schemas, OpenAPI and fixtures together for contract changes.

## Git workflow

Use focused branches such as codex/frontend-upload or codex/backend-search for assistant-created feature work. Keep frontend, backend and shared-contract changes in reviewable commits. Inspect status and diff before committing; stage explicit files and never force-push shared history. Push when the user requests it. Review shared contract PRs together before implementation.
