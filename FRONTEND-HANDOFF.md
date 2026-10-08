# Frontend handoff

Use branch `codex/backend-service` once shared. Implement against SPEC.md **1.1** and contracts/openapi.json; the older frontend plan lacks chat. No frontend files were changed.

## Startup

Install Python 3.12, uv and FFmpeg/ffprobe. From the repository root:

```bash
uv sync --project backend
cp backend/.env.example backend/.env
# Set GEMINI_API_KEY and LOAD_MODELS=true in backend/.env.
# Calibrate RELEVANCE_THRESHOLD on development footage before search.
PYTHONPATH=backend uv run --project backend --env-file backend/.env uvicorn app.main:app --host 127.0.0.1 --port 8000
```

API base is http://localhost:8000; frontend origin defaults to http://localhost:3000. Inspect /docs and /api/v1/health. Keep all Google keys on the backend; the owner's ignored key is absent from this commit. Model startup makes billable smoke requests. Connecting across computers requires an accessible backend host and configured PUBLIC_BASE_URL/FRONTEND_ORIGIN; localhost refers to each computer itself.

## Integration

- Generate TypeScript types from contracts/openapi.json. Use contracts/fixtures in explicitly labelled fixture mode. Successes use the data envelope; errors include error and request_id. Preserve snake_case and explicit nulls.
- Upload multipart file and camera_label to POST /api/v1/videos. Poll the returned preparation job every two seconds. Load video detail, optionally PUT zones, then POST the video's /index route with {} and poll indexing. Support retry and persisted reload recovery.
- POST /api/v1/searches with query, video_ids and optional filters. Poll job/search until terminal. Preserve backend ordering. Render warnings, empty results and errors.
- Use returned media URLs and recording-relative source intervals. Seek after metadata loads and stop at the interval end. Check fresh-video seeking and polygons under letterboxing/resizing.
- Label cosine scores as similarity, never accuracy. Gemini frame checks have yes/no/uncertain decisions and probability_yes null; never invent percentages. Display frame timestamps and verification reasons. Temporal events remain disabled.
- POST /api/v1/chats with ready video_ids, then POST /api/v1/chats/{chat_id}/messages with message. Poll chat detail every two seconds until idle/failed; retain chat_id across refresh. Render returned grounded messages/result references. Follow-up filters retain prior search context.
- Stop polling on terminal state/unmount and guard against stale searches. Keep all AI calls in the backend.

Optional synthetic fixture media:

```bash
PYTHONPATH=backend uv run --project backend python backend/scripts/seed_fixture_media.py
```

This registers media only, not canned live results. Backend checks: `uv run --project backend python -m pytest backend/tests -q`. Real Google smoke checks passed on tiny generated footage; joint AC01–AC09 with consenting staged CCTV and the frontend remains outstanding. See backend/ACCEPTANCE.md. P1 remains deferred.
