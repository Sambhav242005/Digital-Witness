# Combined application QA — 8 October 2026

Tested the production frontend at localhost:3000 with the live backend at localhost:8000, mocks disabled. No new fixes or report changes were committed/pushed during this audit.

## Working

- Browser API connection displays contract 1.1 and persistent recordings.
- Generated MP4 browser upload, preparation, normalized triangle zone editing/save, unsaved-edit indexing guard and indexing succeeded. Reload recovered the ready recording and previous completed search.
- Real public street footage uploaded/prepared/indexed through the browser; preview media loaded with duration 15.448767 seconds, readyState 4 and no media error.
- Generated red-square query returned the correct clip. Source playback was observed advancing. Time filtering retained the original overlapping source interval, as specified.
- Invalid reversed time ranges show validation errors. Empty results display a warning that absence is not proved.
- Real media prefix/suffix ranges returned 206 with correct lengths; out-of-range returned 416. CORS allowed localhost:3000. Disabled event filters rejected with 422 UNSUPPORTED_EVENT_TYPE.
- Backend tests: 127 passed. Frontend tests: 6 passed. TypeScript passed after the previously made local duration null/undefined guard. Lint passed with image warnings. Production build passed when run separately from dev.

## Failing or incomplete

1. Relevant real-footage queries returned zero clips. Actual maximum cosine scores were approximately 0.5908 for person carrying a bag and 0.6590 for people waiting at a pedestrian crossing, below the configured synthetic-development threshold 0.7633429517975161. The unrelated elephant query scored 0.4692 and returned empty. Do not interpret empty positive searches as footage absence. Real development calibration plus held-out evaluation is required; this single clip is insufficient.
2. Live backend chat turn failed with upstream Google ClientError 429 (rate/quota limit). Failure was persisted visibly. Earlier generated-footage chat passed, but current operation is not reliable.
3. Separate native Gemini visual load smoke failed; visual evidence on real footage was not validated. Positive searches were filtered out before frame checks, so no end-to-end real bag evidence was produced.
4. Health capability booleans remain true after this transient upstream chat failure. They describe loaded adapters, not current quota/availability.
5. Frontend has no chat UI or chat API methods despite contract 1.1/backend chat. Temporal tracking/events are explicitly deferred and disabled.
6. npm audit reported 11 dependency vulnerabilities (3 critical, 7 high, 1 moderate), including Next.js, Vitest and transitive packages. Installed Next.js 15.5.4 is affected by the vendor RSC advisory. Dependency upgrade and verification are required before deployment. https://nextjs.org/blog/CVE-2025-66478
7. Frontend README still describes 1.0 and incorrectly says backend/contracts are absent. Types are handwritten and omit health.chat. Next.js infers a workspace root from an unrelated parent lockfile; startup/build emits that warning. CSS flex-end and image-optimization warnings remain.

## Test footage and limits

People waiting to cross the street, by Amada44, CC BY-SA 3.0: https://commons.wikimedia.org/wiki/File:People_waiting_to_cross_the_street.webm . Converted WebM to H.264 MP4 without audio while retaining its time axis. Attribution and local files are in ignored backend/data/internet-qa. Frames were manually inspected to confirm visible pedestrians and bags. Footage is a public handheld street scene, not a representative surveillance benchmark. No identity, ownership or intent inference was tested or claimed.

Not exhaustively browser-tested: resizing/letterboxing, mobile layouts, every keyboard control, slow/offline connectivity, 500 MiB/30-minute boundary footage, all failure/retry paths and long-running restart recovery. Backend automated coverage exercises many of these server cases; it does not replace joint staged-video AC01–AC09 acceptance.

## Next handoff

Backend: calibrate real-footage retrieval; provide informative upstream quota errors/availability; complete real candidate frame-check evaluation. Frontend owner: add chat, synchronize contract types/docs, upgrade affected dependencies, then complete responsive/accessibility/reload/playback acceptance. Preserve the uncommitted duration fix and locally generated lockfile when coordinating changes.

## Fix verification update

- Replaced the ignored local synthetic threshold with 0.5721176865348145, selected by existing clip-F1 calibration on six labeled queries against the public pedestrian clip. Three positive and three unrelated development queries then passed real HTTP retrieval. A separate Editor CC BY3.0 traffic clip passed two positive and two unrelated queries without changing the threshold. Tiny-set recall@5 was1.0 and false positives0; these are not representative CCTV metrics. Labels/measurements are ignored runtime artifacts.
- Added provider cooldown and sanitized quota errors with status/retry delay. Runtime health now reflects cooldown; transient startup failure retries only when due. Google generation quota remains externally unavailable, so bag candidates correctly expose not_checked and VERIFICATION_UNAVAILABLE.
- Added frontend persisted chat, scoped recording selection, follow-ups, two-second polling and evidence links. Disabled capability is shown honestly. Live generated chat completion remains blocked by Google quota; orchestration is verified with explicit mocks in tests.
- Patched runtime/test dependencies and compatible transitive overrides; npm audit now reports zero vulnerabilities. Next tracing root and README contract details were corrected. CSS end-alignment warnings were fixed; image optimization advisories remain.
- Previously made undefined-duration guard is retained. No new commit or push performed for these fixes.

## User-provided demo retest

Tested istockphoto-2289401339-640_adpp_is.mp4 (15.582233 seconds) after updating the ignored backend key. Explicit filename ignore added to .gitignore, and git check-ignore confirmed exclusion. Source and generated test artifacts remain uncommitted.

- Upload/preparation/indexing passed; playback was observed advancing from4seconds via chat evidence links.
- Yellow reflective vest query returned4–12and12–15.58seconds. Parcel query also returnedtwo clips.
- Person-carrying-bag query returnedtwo semantic candidates withthreeframes each. Allsix native Gemini checks answeredno withnull probability; both candidates werecontradicted. No modelquota error occurred during these checks.
- First browserchat answered withretrievedsourceIDs andinspectlinks. After8seconds follow-up preserved thepriorquery andsettime_range8–15.582233; itsretrievalsucceeded, but finalgenerationfailed withGoogle429 andpersistedactionablecooldownerror.
- Unrelated elephantquery returnedonefalsepositive (cosine0.57574 vsconfiguredthreshold0.57212). The public-footage development threshold isnotgeneral enough for thisscene. Do notclaim finalretrievalacceptance or absence ofevents. Furtherrepresentative calibration/heldoutevaluation isneeded.

The demofollowup wasretriedonce aftercooldown and succeeded: chatreturnedidle withnoerror, retainedthevestquery and8–15.582233secondtimefilter, andcitedtwo realretrievedresults. Thisdemonstratesrecovery fromtheobserved429; itdoesnotpromiseunlimitedquotacapacity.
