# Backend handoff and acceptance status

Implemented against SPEC.md v1.1 on 8 October 2026. The user explicitly changed the model setup to Google Gemini chat, embedding and visual decisions; shared specifications and generated contracts were synchronized.

| Criterion | Backend evidence | Remaining acceptance |
|---|---|---|
| AC01 | Real multipart upload, FFmpeg preparation, persisted queue and lifecycle tests; actual Gemini API indexed two generated videos | Consenting staged CCTV footage and frontend workflow |
| AC02 | Simple normalized polygon validation, server persistence and reload tests | Browser letterboxing/resize/keyboard operation |
| AC03 | Selected-video/time filters, ranked source boundaries and range delivery tested; actual Gemini retrieval passed synthetic smoke | Staged CCTV retrieval and frontend seek/end behavior |
| AC04 | Exact evidence/verification schemas and conservative aggregation implemented | Staged Gemini visual evaluation and frontend labels |
| AC05 | Real API unrelated bag query returned empty against geometric footage; development threshold measured | CCTV threshold calibration and held-out evaluation |
| AC06 | Unavailable verification returns warnings/not_checked; poor-frame gate implemented/tested | Real frame readability evaluation |
| AC07 | Preparation/index retry, no queryable partial vectors and interrupted restart tested | Joint workflow review |
| AC08 | Generated OpenAPI and validated lifecycle fixtures exported | Frontend integration against fixtures and live API |
| AC09 | Real H.264 source and full/open/suffix/unsatisfiable byte-range tests pass | Fresh-browser native video seek |
| AC10 | Capability false; unsupported event filters reject | P1 deferred until live P0 passes |

Chat tests additionally verify persisted follow-ups, recording scoping, duplicate-turn rejection, interruption recovery and invented result-reference rejection. SDK request/response shape checks use the installed pinned Google SDK with mocked service responses. Real Gemini 3.5 Flash completed a grounded result explanation and a follow-up retaining the query with a two-second filter. A preceding follow-up failed visibly and resubmission succeeded.

No CCTV accuracy benchmark is claimed. The user supplied the backend key, which is saved only in the ignored local environment. A two-recording/three-query geometric development smoke measured recall@5 1.0, zero false-positive candidates and mean polling-observed search latency 2.02 seconds; this is not held-out CCTV evaluation. Regression tests inject test doubles and do not measure model quality. Consenting calibration/evaluation footage remains needed for final AI acceptance. Gemini native visual smoke passed and decisions expose null probabilities. Model smoke-test and setup details are in MODEL-NOTES.md. Frontend files were not changed. Existing untracked CLAUDE.md and .rtk files were preserved.
