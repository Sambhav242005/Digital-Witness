# Digital Witness frontend

Next.js App Router interface for the Digital Witness v1.1 API. The browser calls FastAPI directly through `src/api/client.ts`; components do not construct API URLs.

## Start

1. Install Node.js 22 LTS (22.12 or newer) or Node.js 24 LTS.
2. Copy `.env.example` to `.env.local` and set the API URL and mock switch.
3. From this directory, run `npm ci`, then `npm run dev`.
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

The FastAPI backend, generated OpenAPI, and canonical fixtures are available in [`../backend/`](../backend/), [`../contracts/openapi.json`](../contracts/openapi.json), and [`../contracts/fixtures/`](../contracts/fixtures/). [`../SPEC.md`](../SPEC.md) v1.1 owns the API contract; the original frontend plan still describes the earlier v1.0 milestone. See [`../FRONTEND-HANDOFF.md`](../FRONTEND-HANDOFF.md) for backend startup and integration details. Set `NEXT_PUBLIC_USE_MOCKS=false` when testing the complete application. Gemini credentials belong only in the backend's ignored environment file.

## Dependency maintenance

Dependencies use exact tested versions and a committed npm lockfile. The runtime stays on patched Next.js 15.5.27 and React 19.1.9. Vitest 4.1.11 fixes a vulnerability that its unmaintained v3 line will not receive. PostCSS 8.5.29 and sharp 0.35.5 overrides replace vulnerable transitive versions bundled by Next.js.

The temporary `eslint-config-next` 14.2.35 pin applies only to development lint rules; the application runs Next.js 15.5.27. The newer Next lint plugin still depends on an unpatched fast-glob/braces chain. The v14 lint package uses glob instead, overridden to patched 10.5.0, while retaining React, hooks, accessibility and Next core-web-vitals checks. Replace this fallback when the current lint plugin has a secure dependency chain. `npm run lint` calls ESLint directly because Next.js is deprecating its lint command. Re-run all checks and `npm audit` when updating dependencies or overrides.

Security references: [Next.js September 2026 release](https://nextjs.org/blog/september-2026-security-release), [Vitest maintained-version advisory](https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9).
