# Digital Witness frontend

Next.js App Router interface for the Digital Witness v1.0 API. The browser calls FastAPI directly through `src/api/client.ts`; components do not construct API URLs.

## Start

1. Install Node.js 20.9 or newer.
2. Copy `.env.example` to `.env.local` and set the API URL and mock switch.
3. From this directory, run `npm install`, then `npm run dev`.
4. Open [http://localhost:3000](http://localhost:3000). The backend must allow this origin in CORS for live requests.

`NEXT_PUBLIC_API_BASE_URL` defaults to `http://localhost:8000/api/v1`. Set `NEXT_PUBLIC_USE_MOCKS=true` to enable the visibly labelled local demo mode. Its temporary recording, job, search, and error data lives in [`demo.json`](demo.json); mock changes persist in browser storage. Clear `dw_mock_videos`, `dw_mock_jobs`, and `dw_mock_searches` in local storage to restore the original demo data. Public environment values are embedded during build, so rebuild after changing production settings. Never put server secrets in frontend variables.

## Checks

- `npm run lint`
- `npm run typecheck`
- `npm test`
- `npm run build`

## Frontend acceptance checklist

- [ ] Upload accepts MP4 selections up to 500 MiB and rejects other formats or oversized files before sending.
- [ ] Preparation and indexing show backend status; absent percentages use an indeterminate indicator.
- [ ] Entrance points use normalized image coordinates, exclude video letterboxing, reproject after resize, and retain on save failure.
- [ ] Unsaved zone edits block indexing; undo, clear, save and skip are keyboard accessible.
- [ ] Search validates the query, selected ready videos, `mm:ss` interval and health-advertised event capability.
- [ ] Result labels, evidence, warnings, empty results and API failures remain distinct and accurate.
- [ ] Playback seeks to the original recording interval after metadata, pauses at its end, and evidence frames seek to their timestamps.
- [ ] New searches replace prior results; the active search ID and active recording jobs recover after refresh.
- [ ] Live mode uses only live API responses and backend-provided absolute media URLs. Verify CORS and Range seeking against the running backend.

## Integration status

The repository currently contains the shared documents but no backend, generated OpenAPI file, or canonical fixture directory. The frontend types follow the v1.0 shapes in `Digital-Witness-SRS.md` / `SPEC.md`. Live upload, media playback, CORS and Range behavior require the backend service; the local mock mode is for interface development only.
