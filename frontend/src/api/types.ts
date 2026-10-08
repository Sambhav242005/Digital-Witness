export type VideoStatus = 'preparing' | 'draft' | 'indexing' | 'ready' | 'failed';
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed';
export type JobKind = 'prepare_video' | 'index_video' | 'search';
export type EventType = 'person_entered' | 'possible_unattended_bag';
export type VerificationStatus = 'supported' | 'uncertain' | 'contradicted' | 'not_checked';
export type JobStage = 'queued' | 'preparing' | 'embedding' | 'detecting' | 'retrieving' | 'verifying' | 'finalizing' | 'complete' | 'failed';
export type Point = { x: number; y: number };
export type Zone = { zone_id: string; name: string; kind: 'entrance'; polygon: Point[] };
export type ApiErrorBody = { code: string; message: string; details: Record<string, unknown> };

export type Video = {
  video_id: string;
  filename: string;
  camera_label: string;
  status: VideoStatus;
  created_at: string;
  duration_sec: number | null;
  width: number | null;
  height: number | null;
  playback_url: string | null;
  thumbnail_url: string | null;
  zones: Zone[];
  active_job_id: string | null;
  error: ApiErrorBody | null;
};

export type Job = {
  job_id: string;
  kind: JobKind;
  resource_id: string;
  status: JobStatus;
  stage: JobStage;
  progress_pct: number;
  created_at: string;
  updated_at: string;
  error: ApiErrorBody | null;
};

export type FrameCheck = { check_id: string; question: string; answer: 'yes' | 'no' | 'uncertain'; probability_yes: number | null };
export type EvidenceFrame = { timestamp_sec: number; image_url: string; quality: 'usable' | 'poor'; checks: FrameCheck[] };
export type SearchResult = {
  result_id: string;
  video_id: string;
  camera_label: string;
  start_sec: number;
  end_sec: number;
  thumbnail_url: string;
  playback_url: string;
  summary: string;
  event_type: EventType | null;
  zone_id: string | null;
  retrieval_score: number;
  verification: { status: VerificationStatus; reason: string; basis: 'frame_checks' | 'temporal_rule' | 'none' };
  evidence: EvidenceFrame[];
};

export type SearchRequest = {
  query: string;
  video_ids: string[];
  limit?: number;
  time_range?: { start_sec: number; end_sec: number };
  event_types?: EventType[];
};

export type Search = {
  search_id: string;
  job_id: string;
  status: JobStatus;
  query: string;
  video_ids: string[];
  created_at: string;
  warnings: { code: string; message: string }[];
  results: SearchResult[];
  error: ApiErrorBody | null;
};

export type Health = {
  status: 'ok';
  contract_version: string;
  mode: 'live' | 'mock';
  capabilities: { semantic_search: boolean; frame_verification: boolean; temporal_events: boolean };
  supported_event_types: EventType[];
};

export type VideoPage = { items: Video[]; total: number; limit: number; offset: number };
export type AcceptedVideo = { video: Video; job: Job };
export type AcceptedSearch = { search_id: string; job: Job };
export type ZoneInput = { name: string; kind: 'entrance'; polygon: Point[] };
