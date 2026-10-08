import { ApiError } from './errors';
import type { ApiClient } from './client';
import type { AcceptedSearch, AcceptedVideo, EventType, Health, Job, Search, SearchRequest, Video, VideoPage, ZoneInput } from './types';
import { fixtureJobs, fixtureSearches, fixtureVideos } from './fixtures';

const now = () => new Date().toISOString();
const media = 'http://localhost:8000/api/v1/media';
const thumb = (name: string) => `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="720" height="405"><defs><linearGradient id="g"><stop stop-color="#17292c"/><stop offset="1" stop-color="#394d48"/></linearGradient></defs><rect width="100%" height="100%" fill="url(#g)"/><path d="M0 290h720M120 0v405M570 0v405" stroke="#7e9485" stroke-opacity=".34"/><circle cx="390" cy="180" r="24" fill="#d5ad77"/><text x="24" y="370" fill="#e9e4d9" font-family="sans-serif" font-size="18">${name}</text></svg>`)}`;

function baseVideo(videoId: string, status: Video['status'], cameraLabel: string, filename: string): Video {
  return { video_id: videoId, filename, camera_label: cameraLabel, status, created_at: now(), duration_sec: status === 'preparing' ? null : 142, width: status === 'preparing' ? null : 1920, height: status === 'preparing' ? null : 1080, playback_url: status === 'draft' || status === 'ready' ? `${media}/video_${videoId}` : null, thumbnail_url: status === 'preparing' ? null : thumb(cameraLabel), zones: [], active_job_id: null, error: null };
}

const seededVideos: Video[] = fixtureVideos;

function readVideos(): Video[] {
  if (typeof window === 'undefined') return seededVideos;
  try {
    const saved = window.localStorage.getItem('dw_mock_videos');
    return saved ? JSON.parse(saved) as Video[] : seededVideos;
  } catch { return seededVideos; }
}

function writeVideos(videos: Video[]) {
  if (typeof window !== 'undefined') window.localStorage.setItem('dw_mock_videos', JSON.stringify(videos));
}

function makeJob(kind: Job['kind'], resourceId: string, status: Job['status'] = 'queued', stage: Job['stage'] = 'queued'): Job {
  return { job_id: `job_${Math.random().toString(36).slice(2, 10)}`, kind, resource_id: resourceId, status, stage, progress_pct: 0, created_at: now(), updated_at: now(), error: null };
}

const jobs = new Map<string, { job: Job; ticks: number; forceFailure?: boolean }>(fixtureJobs.map((job) => [job.job_id, { job, ticks: job.status === 'queued' ? 0 : 1 }]));
const searches = new Map<string, Search>(fixtureSearches.map((search) => [search.search_id, search]));
let mockStateHydrated = false;

function hydrateMockState() {
  if (mockStateHydrated || typeof window === 'undefined') return;
  mockStateHydrated = true;
  try {
    const savedJobs = window.localStorage.getItem('dw_mock_jobs');
    const savedSearches = window.localStorage.getItem('dw_mock_searches');
    if (savedJobs) for (const [jobId, item] of JSON.parse(savedJobs) as [string, { job: Job; ticks: number; forceFailure?: boolean }][]) jobs.set(jobId, item);
    if (savedSearches) for (const [searchId, search] of JSON.parse(savedSearches) as [string, Search][]) searches.set(searchId, search);
  } catch {
    window.localStorage.removeItem('dw_mock_jobs');
    window.localStorage.removeItem('dw_mock_searches');
  }
}

function persistJobs() {
  if (typeof window !== 'undefined') window.localStorage.setItem('dw_mock_jobs', JSON.stringify([...jobs.entries()]));
}

function persistSearches() {
  if (typeof window !== 'undefined') window.localStorage.setItem('dw_mock_searches', JSON.stringify([...searches.entries()]));
}

function progress(jobId: string): Job {
  const item = jobs.get(jobId);
  if (!item) throw new ApiError({ status: 404, error: { code: 'JOB_NOT_FOUND', message: 'Processing job was not found.', details: { job_id: jobId } } });
  if (item.job.status === 'succeeded' || item.job.status === 'failed') return item.job;
  item.ticks += 1;
  const step = item.ticks;
  const failed = item.forceFailure && step >= 3;
  const terminal = step >= 4 || failed;
  const stages: Job['stage'][] = ['queued', item.job.kind === 'search' ? 'retrieving' : item.job.kind === 'prepare_video' ? 'preparing' : 'embedding', item.job.kind === 'search' ? 'verifying' : 'finalizing', 'complete'];
  item.job = { ...item.job, status: failed ? 'failed' : terminal ? 'succeeded' : step === 1 ? 'queued' : 'running', stage: failed ? 'failed' : terminal ? 'complete' : stages[Math.min(step, 2)], progress_pct: failed ? item.job.progress_pct : terminal ? 100 : [0, 18, 61, 88][step], updated_at: now(), error: failed ? { code: 'SEARCH_FAILED', message: 'The mock search failed. Submit a new search to try again.', details: {} } : item.job.error };
  persistJobs();
  return item.job;
}

export const mockApi: ApiClient = {
  async health(): Promise<Health> { hydrateMockState(); return { status: 'ok', contract_version: '1.0', mode: 'mock', capabilities: { semantic_search: true, frame_verification: true, temporal_events: false }, supported_event_types: [] }; },
  async listVideos(limit, offset): Promise<VideoPage> { hydrateMockState(); const videos = readVideos(); return { items: videos.slice(offset, offset + limit), total: videos.length, limit, offset }; },
  async getVideo(videoId) { hydrateMockState(); const video = readVideos().find((entry) => entry.video_id === videoId); if (!video) throw new ApiError({ status: 404, error: { code: 'VIDEO_NOT_FOUND', message: 'Recording was not found.', details: { video_id: videoId } } }); return video; },
  async uploadVideo(file, cameraLabel): Promise<AcceptedVideo> {
    hydrateMockState();
    const id = `vid_${Math.random().toString(36).slice(2, 9)}`;
    const video = baseVideo(id, 'preparing', cameraLabel, file.name);
    const job = makeJob('prepare_video', id);
    jobs.set(job.job_id, { job, ticks: 0 });
    persistJobs();
    const activeVideo = { ...video, active_job_id: job.job_id };
    writeVideos([activeVideo, ...readVideos()]);
    return { video: activeVideo, job };
  },
  async saveZones(videoId, zones: ZoneInput[]) {
    hydrateMockState();
    const videos = readVideos();
    const index = videos.findIndex((entry) => entry.video_id === videoId);
    if (index < 0) throw new ApiError({ status: 404, error: { code: 'VIDEO_NOT_FOUND', message: 'Recording was not found.', details: {} } });
    if (videos[index].status !== 'draft' && !(videos[index].status === 'failed' && videos[index].playback_url)) throw new ApiError({ status: 409, error: { code: 'INVALID_STATE', message: 'Zones can only be changed before indexing.', details: {} } });
    const updated = { ...videos[index], zones: zones.map((zone, i) => ({ ...zone, zone_id: `zone_${videoId}_${i}` })) };
    videos[index] = updated;
    writeVideos(videos);
    return updated;
  },
  async indexVideo(videoId) { return startVideoJob(videoId, 'index_video'); },
  async retryVideo(videoId) { const video = await this.getVideo(videoId); return startVideoJob(videoId, video.playback_url ? 'index_video' : 'prepare_video'); },
  async getJob(jobId) {
    hydrateMockState();
    const job = progress(jobId);
    const video = readVideos().find((entry) => entry.active_job_id === jobId || entry.video_id === job.resource_id);
    if (job.kind !== 'search' && video) {
      const videos = readVideos();
      const index = videos.findIndex((entry) => entry.video_id === video.video_id);
      const updated: Video = job.status === 'succeeded' ? job.kind === 'prepare_video' ? { ...videos[index], status: 'draft', active_job_id: null, duration_sec: 142, width: 1920, height: 1080, playback_url: `${media}/video_${video.video_id}`, thumbnail_url: thumb(video.camera_label) } : { ...videos[index], status: 'ready', active_job_id: null } : { ...videos[index], status: job.kind === 'prepare_video' ? 'preparing' : 'indexing', active_job_id: jobId };
      videos[index] = updated;
      writeVideos(videos);
    }
    if (job.kind === 'search' && (job.status === 'succeeded' || job.status === 'failed')) {
      const search = searches.get(job.resource_id);
      if (search) { searches.set(job.resource_id, { ...search, status: job.status, error: job.error }); persistSearches(); }
    }
    return job;
  },
  async createSearch(request: SearchRequest): Promise<AcceptedSearch> {
    hydrateMockState();
    const searchId = `search_${Math.random().toString(36).slice(2, 9)}`;
    const job = makeJob('search', searchId);
    jobs.set(job.job_id, { job, ticks: 0 });
    const readyVideo = readVideos().find((entry) => entry.video_id === request.video_ids[0]);
    const isEmpty = /nothing|empty|unrelated|no match/i.test(request.query);
    const isDegraded = /degraded/i.test(request.query);
    const isUncertain = /uncertain/i.test(request.query);
    const isContradicted = /contradicted/i.test(request.query);
    const shouldFail = /fail/i.test(request.query);
    const demoResult = fixtureSearches.find((search) => search.search_id === 'search_demo_populated')?.results[0];
    const result = {
      result_id: `result_${searchId}`, video_id: readyVideo?.video_id ?? 'vid_demo_entrance', camera_label: readyVideo?.camera_label ?? 'North entrance', start_sec: 32, end_sec: 40,
      thumbnail_url: thumb('Evidence frame'), playback_url: readyVideo?.playback_url ?? `${media}/video_vid_ready_01`, summary: demoResult?.summary ?? 'Candidate clip: a person appears to carry a bag. Entrance proximity and temporal actions are unverified.',
      event_type: null, zone_id: null, retrieval_score: 0.72, verification: isDegraded ? { status: 'not_checked' as const, basis: 'none' as const, reason: 'Frame verification is unavailable in this degraded fixture.' } : isUncertain ? { status: 'uncertain' as const, basis: 'frame_checks' as const, reason: 'The sampled frame quality does not support a confident visual check.' } : isContradicted ? { status: 'contradicted' as const, basis: 'frame_checks' as const, reason: 'The sampled frame did not support the requested visible attribute.' } : { status: 'supported' as const, basis: 'frame_checks' as const, reason: 'Supports bag carrying in a sampled frame only; entrance proximity and temporal actions are unverified.' },
      evidence: [{ ...(demoResult?.evidence[0] ?? { timestamp_sec: 35, quality: 'usable' as const, checks: [] }), image_url: thumb('Frame at 00:35') }],
    };
    if (shouldFail) jobs.set(job.job_id, { job, ticks: 1, forceFailure: true });
    persistJobs();
    searches.set(searchId, { search_id: searchId, job_id: job.job_id, status: 'queued', query: request.query, video_ids: request.video_ids, created_at: now(), warnings: isDegraded ? [{ code: 'VERIFICATION_UNAVAILABLE', message: 'Frame verification is unavailable; semantic candidates are shown without verification.' }] : [], results: isEmpty ? [] : [result], error: null });
    persistSearches();
    return { search_id: searchId, job };
  },
  async getSearch(searchId) { hydrateMockState(); const search = searches.get(searchId); if (!search) throw new ApiError({ status: 404, error: { code: 'SEARCH_NOT_FOUND', message: 'Search was not found. Submit it again to create a new search.', details: {} } }); return search; },
};

function startVideoJob(videoId: string, kind: 'prepare_video' | 'index_video'): AcceptedVideo {
  hydrateMockState();
  const videos = readVideos();
  const index = videos.findIndex((entry) => entry.video_id === videoId);
  if (index < 0) throw new ApiError({ status: 404, error: { code: 'VIDEO_NOT_FOUND', message: 'Recording was not found.', details: {} } });
  if (videos[index].active_job_id) throw new ApiError({ status: 409, error: { code: 'JOB_ALREADY_RUNNING', message: 'A job is already running for this recording.', details: {} } });
  const job = makeJob(kind, videoId);
  jobs.set(job.job_id, { job, ticks: 0 });
  persistJobs();
  const video = { ...videos[index], status: kind === 'prepare_video' ? 'preparing' as const : 'indexing' as const, active_job_id: job.job_id, error: null };
  videos[index] = video;
  writeVideos(videos);
  return { video, job };
}

export const mockFixtureCatalog: { videoStates: Video['status'][]; jobStates: Job['status'][]; searchStates: string[]; errorStatuses: number[]; eventTypes: EventType[] } = {
  videoStates: ['preparing', 'draft', 'indexing', 'ready', 'failed'], jobStates: ['queued', 'running', 'succeeded', 'failed'],
  searchStates: ['populated', 'empty', 'degraded', 'failed'], errorStatuses: [409, 422, 503], eventTypes: ['person_entered', 'possible_unattended_bag'],
};
