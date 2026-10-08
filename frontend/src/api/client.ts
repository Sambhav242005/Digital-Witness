import { ApiError, parseApiError } from './errors';
import type { AcceptedSearch, AcceptedVideo, Health, Job, Search, SearchRequest, Video, VideoPage, ZoneInput } from './types';

export interface ApiClient {
  health(): Promise<Health>;
  listVideos(limit: number, offset: number): Promise<VideoPage>;
  getVideo(videoId: string): Promise<Video>;
  uploadVideo(file: File, cameraLabel: string): Promise<AcceptedVideo>;
  saveZones(videoId: string, zones: ZoneInput[]): Promise<Video>;
  indexVideo(videoId: string): Promise<AcceptedVideo>;
  retryVideo(videoId: string): Promise<AcceptedVideo>;
  getJob(jobId: string): Promise<Job>;
  createSearch(request: SearchRequest): Promise<AcceptedSearch>;
  getSearch(searchId: string): Promise<Search>;
}

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '');

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, cache: 'no-store' });
  } catch {
    throw new ApiError({ status: 0, error: { code: 'NETWORK_ERROR', message: 'Could not reach the Digital Witness API. Check the backend connection and try again.', details: {} } });
  }
  if (!response.ok) throw await parseApiError(response);
  const envelope = await response.json() as { data: T };
  return envelope.data;
}

export const liveApi: ApiClient = {
  health: () => request<Health>('/health'),
  listVideos: (limit, offset) => request<VideoPage>(`/videos?limit=${limit}&offset=${offset}`),
  getVideo: (videoId) => request<Video>(`/videos/${encodeURIComponent(videoId)}`),
  async uploadVideo(file, cameraLabel) {
    const form = new FormData();
    form.append('file', file);
    form.append('camera_label', cameraLabel);
    return request<AcceptedVideo>('/videos', { method: 'POST', body: form });
  },
  saveZones: (videoId, zones) => request<Video>(`/videos/${encodeURIComponent(videoId)}/zones`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ zones }) }),
  indexVideo: (videoId) => request<AcceptedVideo>(`/videos/${encodeURIComponent(videoId)}/index`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }),
  retryVideo: (videoId) => request<AcceptedVideo>(`/videos/${encodeURIComponent(videoId)}/retry`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }),
  getJob: (jobId) => request<Job>(`/jobs/${encodeURIComponent(jobId)}`),
  createSearch: (search) => request<AcceptedSearch>('/searches', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(search) }),
  getSearch: (searchId) => request<Search>(`/searches/${encodeURIComponent(searchId)}`),
};

const useMocks = process.env.NEXT_PUBLIC_USE_MOCKS === 'true';

async function activeClient(): Promise<ApiClient> {
  if (useMocks) return (await import('./mock')).mockApi;
  return liveApi;
}

export const api: ApiClient = {
  health: async () => (await activeClient()).health(),
  listVideos: async (limit, offset) => (await activeClient()).listVideos(limit, offset),
  getVideo: async (videoId) => (await activeClient()).getVideo(videoId),
  uploadVideo: async (file, cameraLabel) => (await activeClient()).uploadVideo(file, cameraLabel),
  saveZones: async (videoId, zones) => (await activeClient()).saveZones(videoId, zones),
  indexVideo: async (videoId) => (await activeClient()).indexVideo(videoId),
  retryVideo: async (videoId) => (await activeClient()).retryVideo(videoId),
  getJob: async (jobId) => (await activeClient()).getJob(jobId),
  createSearch: async (search) => (await activeClient()).createSearch(search),
  getSearch: async (searchId) => (await activeClient()).getSearch(searchId),
};
