'use client';

import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent, type PointerEvent } from 'react';
import { ApiError } from '@/api/errors';
import { api } from '@/api/client';
import { ChatPanel } from './chat';
import { parseRecordingTime, polygonError, validateVideoSelection, verificationLabel } from '@/api/validation';
import type { EventType, Health, Job, Point, Search, SearchResult, Video, VideoStatus, ZoneInput } from '@/api/types';

const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === 'true';
const PAGE_SIZE = 20;
const POLL_MS = 2000;
const statusCopy: Record<VideoStatus, string> = { preparing: 'Preparing', draft: 'Ready for zone setup', indexing: 'Indexing', ready: 'Ready', failed: 'Failed' };
const eventNames: Record<EventType, string> = { person_entered: 'Person entered', possible_unattended_bag: 'Possible unattended bag' };

function formatTime(seconds: number | null | undefined) {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  const total = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}

function apiErrorMessage(error: unknown): string {
  if (!(error instanceof Error)) return 'The request could not be completed.';
  if (!(error instanceof ApiError)) return error.message;
  if (error.status === 429 && error.retryAfterSec !== null) return `${error.message} Try again in ${error.retryAfterSec} seconds.`;
  if (error.status === 422 && Object.keys(error.details).length) return `${error.message} Details: ${JSON.stringify(error.details)}`;
  if (error.requestId) return `${error.message} Request ID: ${error.requestId}`;
  return error.message;
}

function StatusPill({ status }: { status: VideoStatus }) {
  return <span className={`status-pill status-${status}`}><span aria-hidden="true" className="status-dot" />{statusCopy[status]}</span>;
}

function ErrorNotice({ error, action }: { error: string; action?: React.ReactNode }) {
  return <div className="error-notice" role="alert"><span className="error-mark" aria-hidden="true">!</span><div><strong>Something needs attention</strong><p>{error}</p>{action}</div></div>;
}

function Progress({ job }: { job: Job }) {
  const pct = Number.isFinite(job.progress_pct) ? Math.min(100, Math.max(0, job.progress_pct)) : null;
  return <div className="progress-wrap"><div className="progress-label"><span>{job.stage.replaceAll('_', ' ')}</span>{pct === null ? <span>In progress</span> : <span>{pct}% estimated</span>}</div>{pct === null ? <div className="progress-track"><span className="progress-indeterminate" /></div> : <div className="progress-track"><span className="progress-value" style={{ width: `${pct}%` }} /></div>}</div>;
}

function ZoneEditor({ video, onSaved, onStart, busy }: { video: Video; onSaved: (video: Video) => void; onStart: (video: Video) => void; busy: boolean }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const [points, setPoints] = useState<Point[]>(video.zones[0]?.polygon ?? []);
  const [savedPoints, setSavedPoints] = useState<Point[]>(video.zones[0]?.polygon ?? []);
  const [imageRect, setImageRect] = useState({ left: 0, top: 0, width: 1, height: 1 });
  const [saving, setSaving] = useState(false);
  const [zoneError, setZoneError] = useState('');
  const [drawing, setDrawing] = useState(true);
  const editable = video.status === 'draft' || (video.status === 'failed' && video.playback_url !== null);
  const dirty = JSON.stringify(points) !== JSON.stringify(savedPoints);
  const canIndex = editable && !dirty && !saving && !busy;

  useEffect(() => {
    const node = frameRef.current;
    const mediaNode = videoRef.current;
    if (!node || !mediaNode) return;
    const update = () => {
      const bounds = node.getBoundingClientRect();
      const sourceWidth = mediaNode.videoWidth || video.width || bounds.width;
      const sourceHeight = mediaNode.videoHeight || video.height || bounds.height;
      const scale = Math.min(bounds.width / sourceWidth, bounds.height / sourceHeight);
      const width = sourceWidth * scale;
      const height = sourceHeight * scale;
      setImageRect({ left: (bounds.width - width) / 2, top: (bounds.height - height) / 2, width, height });
    };
    const observer = new ResizeObserver(update);
    observer.observe(node);
    mediaNode.addEventListener('loadedmetadata', update);
    update();
    return () => { observer.disconnect(); mediaNode.removeEventListener('loadedmetadata', update); };
  }, [video.playback_url, video.width, video.height]);

  useEffect(() => {
    const existing = video.zones[0]?.polygon ?? [];
    setPoints(existing);
    setSavedPoints(existing);
    setZoneError('');
  }, [video.video_id, video.zones]);

  const addPoint = (event: PointerEvent<HTMLDivElement>) => {
    if (!editable || !drawing || saving || points.length >= 12 || !frameRef.current) return;
    const bounds = frameRef.current.getBoundingClientRect();
    const x = event.clientX - bounds.left - imageRect.left;
    const y = event.clientY - bounds.top - imageRect.top;
    if (x < 0 || y < 0 || x > imageRect.width || y > imageRect.height) return;
    setPoints((existing) => [...existing, { x: Number((x / imageRect.width).toFixed(5)), y: Number((y / imageRect.height).toFixed(5)) }]);
    setZoneError('');
  };

  const save = async () => {
    if (points.length) {
      const validationError = polygonError(points);
      if (validationError) { setZoneError(validationError); return; }
    }
    setSaving(true);
    setZoneError('');
    try {
      const zones: ZoneInput[] = points.length ? [{ name: 'Main entrance', kind: 'entrance', polygon: points }] : [];
      const updated = await api.saveZones(video.video_id, zones);
      setSavedPoints(points);
      onSaved(updated);
    } catch (error) { setZoneError(apiErrorMessage(error)); }
    finally { setSaving(false); }
  };

  const skip = async () => {
    if (saving || busy) return;
    setSaving(true);
    setZoneError('');
    try {
      if (video.zones.length) onSaved(await api.saveZones(video.video_id, []));
      setPoints([]);
      setSavedPoints([]);
      onStart({ ...video, zones: [] });
    } catch (error) { setZoneError(apiErrorMessage(error)); }
    finally { setSaving(false); }
  };

  const projected = points.map((point) => `${imageRect.left + point.x * imageRect.width},${imageRect.top + point.y * imageRect.height}`).join(' ');
  return <section className="panel zone-panel" aria-labelledby="zone-heading">
    <div className="section-heading"><div><span className="eyebrow">PREVIEW & ZONE</span><h2 id="zone-heading">{video.camera_label}</h2><p>Mark one entrance area, or skip this step.</p></div><StatusPill status={video.status} /></div>
    <div className="video-frame" ref={frameRef} onPointerDown={addPoint} role={editable ? 'application' : undefined} tabIndex={editable ? 0 : undefined} aria-label={editable ? 'Entrance drawing surface. Press Enter to add a center point or Backspace to undo.' : 'Recording preview'} onKeyDown={(event) => {
      if (!editable || !drawing) return;
      if ((event.key === 'Enter' || event.key === ' ') && points.length < 12) { event.preventDefault(); setPoints((current) => [...current, { x: 0.5, y: 0.5 }]); }
      if (event.key === 'Backspace' || event.key === 'Delete') { event.preventDefault(); setPoints((current) => current.slice(0, -1)); }
    }}>
      {video.playback_url ? <video ref={videoRef} src={video.playback_url} controls={!editable || !drawing} preload="metadata" aria-label={`${video.camera_label} recording preview`} /> : <div className="video-placeholder"><span className="play-symbol">▶</span><span>Preview is available after preparation</span></div>}
      {editable && <svg className="zone-overlay" aria-hidden="true"><polygon points={projected} /><polyline points={projected} />{points.map((point, index) => <circle key={`${point.x}-${point.y}-${index}`} cx={imageRect.left + point.x * imageRect.width} cy={imageRect.top + point.y * imageRect.height} r="7" />)}</svg>}
      {editable && drawing && <span className="frame-hint">Click to add point · {points.length}/12</span>}
    </div>
    {editable && <div className="zone-controls">
      <div className="zone-mode-row"><span className="helper-text">{drawing ? 'Drawing mode · normalized image coordinates' : 'Preview mode · use native video controls'}</span><button className="text-button" type="button" onClick={() => setDrawing((current) => !current)}>{drawing ? 'Preview recording' : 'Mark entrance points'}</button></div>
      <div className="zone-point-list" aria-label="Entrance polygon coordinates">{points.map((point, index) => <div className="point-input" key={`${index}-${point.x}`}><label>Point {index + 1} X<input aria-label={`Point ${index + 1} horizontal coordinate`} type="number" min="0" max="1" step="0.01" value={point.x} onChange={(event) => setPoints((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, x: Math.min(1, Math.max(0, Number(event.target.value))) } : item))} /></label><label>Y<input aria-label={`Point ${index + 1} vertical coordinate`} type="number" min="0" max="1" step="0.01" value={point.y} onChange={(event) => setPoints((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, y: Math.min(1, Math.max(0, Number(event.target.value))) } : item))} /></label></div>)}</div>
      <div className="button-row"><button className="button button-quiet" type="button" disabled={points.length >= 12 || saving} onClick={() => { setDrawing(true); setPoints((current) => [...current, { x: 0.5, y: 0.5 }]); }}>Add center point</button><button className="button button-quiet" type="button" disabled={!points.length || saving} onClick={() => setPoints((current) => current.slice(0, -1))}>Undo point</button><button className="button button-quiet" type="button" disabled={!points.length || saving} onClick={() => setPoints([])}>Clear</button><button className="button button-secondary" type="button" disabled={!dirty || saving} onClick={save}>{saving ? 'Saving…' : points.length ? 'Save entrance' : 'Save cleared zone'}</button></div>
      {dirty && <p className="inline-warning">Save or clear these edits before indexing.</p>}
      {zoneError && <p className="field-error" role="alert">{zoneError}</p>}
      <div className="button-row zone-footer"><button className="button button-primary" type="button" disabled={!canIndex} onClick={() => onStart(video)}>{video.status === 'failed' ? 'Retry indexing' : 'Start indexing'}</button><button className="button button-quiet" type="button" disabled={busy || saving} onClick={skip}>{video.status === 'failed' ? 'Skip zone & retry' : 'Skip zone & index'}</button></div>
    </div>}
    {!editable && video.status === 'ready' && <div className="zone-readonly"><span>Entrance saved</span><span>{video.zones[0] ? 'One entrance · read-only after indexing' : 'No entrance zone was used'}</span></div>}
  </section>;
}

function EvidencePlayer({ result }: { result: SearchResult | null }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pendingSeek = useRef<{ time: number; autoplay: boolean } | null>(null);
  const [playError, setPlayError] = useState(false);
  const [continueRecording, setContinueRecording] = useState(false);
  useEffect(() => {
    pendingSeek.current = null;
    setPlayError(false);
    setContinueRecording(false);
  }, [result?.result_id]);

  const seek = (time: number, autoplay: boolean) => {
    const video = videoRef.current;
    if (!video) return;
    setPlayError(false);
    const performSeek = () => {
      video.currentTime = time;
      if (autoplay) void video.play().catch(() => setPlayError(true));
    };
    if (video.readyState >= 1) performSeek();
    else pendingSeek.current = { time, autoplay };
  };
  const onMetadata = () => {
    const video = videoRef.current;
    if (!video || !result) return;
    const requested = pendingSeek.current;
    pendingSeek.current = null;
    video.currentTime = requested?.time ?? result.start_sec;
    if (requested?.autoplay) void video.play().catch(() => setPlayError(true));
  };
  const openResult = () => { if (result) seek(result.start_sec, true); };
  const onTimeUpdate = () => {
    const video = videoRef.current;
    if (result && video && !continueRecording && video.currentTime >= result.end_sec) video.pause();
  };
  const selectEvidence = (timestamp: number) => seek(timestamp, true);

  return <section className="panel player-panel" aria-labelledby="player-heading">
    <div className="section-heading"><div><span className="eyebrow">SOURCE PLAYBACK</span><h2 id="player-heading">{result ? result.camera_label : 'Select a moment'}</h2><p>{result ? `${formatTime(result.start_sec)}–${formatTime(result.end_sec)} · original recording timeline` : 'Search results open in the source recording.'}</p></div><span className="source-mark">SOURCE</span></div>
    <div className="player-shell">
      {result ? <video key={result.result_id} ref={videoRef} src={result.playback_url} controls preload="metadata" onTimeUpdate={onTimeUpdate} onLoadedMetadata={onMetadata} aria-label={`Source recording for ${result.camera_label}`} /> : <div className="player-empty"><span className="play-symbol">▶</span><span>Evidence playback appears here</span></div>}
    </div>
    {result && <div className="player-actions"><button className="button button-primary" type="button" onClick={openResult}>Play evidence interval</button><label className="check-label"><input type="checkbox" checked={continueRecording} onChange={(event) => setContinueRecording(event.target.checked)} />Continue recording after interval</label>{playError && <span className="field-error" role="status">Playback did not start. Use the video Play control.</span>}</div>}
    {result && <div className="evidence-block"><div className="evidence-heading"><h3>Evidence frames</h3><span>{result.evidence.length} sampled</span></div>{result.evidence.length ? <div className="evidence-list">{result.evidence.map((frame) => <button type="button" className="evidence-frame" key={`${frame.timestamp_sec}-${frame.image_url}`} onClick={() => selectEvidence(frame.timestamp_sec)}><img src={frame.image_url} alt={`Evidence at ${formatTime(frame.timestamp_sec)}`} /><span>{formatTime(frame.timestamp_sec)}</span></button>)}</div> : <p className="muted-copy">No evidence frames were provided for this result.</p>}</div>}
  </section>;
}

export default function Workspace() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);
  const [selectedResult, setSelectedResult] = useState<SearchResult | null>(null);
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [appError, setAppError] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [cameraLabel, setCameraLabel] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [searchText, setSearchText] = useState('');
  const [selectedVideoIds, setSelectedVideoIds] = useState<string[]>([]);
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [eventTypes, setEventTypes] = useState<EventType[]>([]);
  const [search, setSearch] = useState<Search | null>(null);
  const [searchError, setSearchError] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchJob, setSearchJob] = useState<Job | null>(null);
  const searchGeneration = useRef(0);
  const retryNotBefore = useRef(0);
  const pollFailures = useRef(0);

  const deferPolling = useCallback((error: unknown) => {
    pollFailures.current += 1;
    const serverDelay = error instanceof ApiError && error.status === 429 ? error.retryAfterSec : null;
    const delay = serverDelay !== null ? Math.max(POLL_MS, serverDelay * 1000) : Math.min(30000, POLL_MS * 2 ** Math.min(pollFailures.current, 4));
    retryNotBefore.current = Date.now() + delay;
  }, []);

  const resetPollingDelay = useCallback(() => { pollFailures.current = 0; retryNotBefore.current = 0; }, []);

  const selectedVideo = videos.find((video) => video.video_id === selectedVideoId) ?? null;
  const readyVideos = useMemo(() => videos.filter((video) => video.status === 'ready'), [videos]);
  const reload = useCallback(async (offset = page * PAGE_SIZE) => {
    setLoading(true);
    try {
      const [healthData, pageData] = await Promise.all([api.health(), api.listVideos(PAGE_SIZE, offset)]);
      const recoveredVideos = await Promise.all(pageData.items.map((video) => video.active_job_id ? api.getVideo(video.video_id).catch(() => video) : video));
      setHealth(healthData);
      setVideos(recoveredVideos);
      setTotal(pageData.total);
      setAppError('');
      setSelectedVideoId((current) => current && recoveredVideos.some((entry) => entry.video_id === current) ? current : recoveredVideos[0]?.video_id ?? null);
      setJobs((current) => {
        const recovered = { ...current };
        for (const video of recoveredVideos) if (video.active_job_id && !recovered[video.active_job_id]) recovered[video.active_job_id] = { job_id: video.active_job_id, kind: video.status === 'preparing' ? 'prepare_video' : 'index_video', resource_id: video.video_id, status: 'running', stage: video.status === 'preparing' ? 'preparing' : 'embedding', progress_pct: Number.NaN, created_at: video.created_at, updated_at: video.created_at, error: null };
        return recovered;
      });
    } catch (error) { setAppError(apiErrorMessage(error)); }
    finally { setLoading(false); }
  }, [page]);

  useEffect(() => { void reload(); }, [reload]);

  useEffect(() => {
    const savedSearchId = window.sessionStorage.getItem('dw_active_search_id');
    if (!savedSearchId) return;
    const generation = searchGeneration.current;
    let active = true;
    void api.getSearch(savedSearchId).then(async (recovered) => {
      if (!active || generation !== searchGeneration.current) return;
      setSearch(recovered);
      if (recovered.status === 'queued' || recovered.status === 'running') {
        const recoveredJob = await api.getJob(recovered.job_id);
        if (active && generation === searchGeneration.current) {
          setSearchJob(recoveredJob);
          setSearching(recoveredJob.status === 'queued' || recoveredJob.status === 'running');
          if (recoveredJob.status === 'succeeded' || recoveredJob.status === 'failed') {
            const latest = await api.getSearch(savedSearchId);
            if (active && generation === searchGeneration.current) setSearch(latest);
          }
        }
      }
    }).catch((error) => {
      if (generation !== searchGeneration.current) return;
      if (error instanceof ApiError && error.status === 404) window.sessionStorage.removeItem('dw_active_search_id');
      else setSearchError(apiErrorMessage(error));
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const activeJobs = Object.values(jobs).filter((job) => job.status === 'queued' || job.status === 'running');
    if (!activeJobs.length) return;
    const timer = window.setInterval(() => {
      if (Date.now() < retryNotBefore.current) return;
      for (const oldJob of activeJobs) void api.getJob(oldJob.job_id).then((fresh) => {
        resetPollingDelay();
        setJobs((current) => ({ ...current, [fresh.job_id]: fresh }));
        if (fresh.status === 'succeeded' || fresh.status === 'failed') void reload();
        if (search && fresh.job_id === search.job_id) {
          setSearchJob(fresh);
          if (fresh.status === 'succeeded') void api.getSearch(search.search_id).then(setSearch).catch((error) => setSearchError(error.message));
          if (fresh.status === 'failed') { setSearching(false); void api.getSearch(search.search_id).then(setSearch).catch(() => setSearchError(fresh.error?.message ?? 'Search failed.')); }
        }
      }).catch((error) => { deferPolling(error); setAppError(apiErrorMessage(error)); });
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [deferPolling, jobs, reload, resetPollingDelay, search]);

  useEffect(() => {
    if (!searching || !searchJob || searchJob.status === 'succeeded' || searchJob.status === 'failed') { if (searchJob?.status === 'succeeded') setSearching(false); return; }
    const generation = searchGeneration.current;
    const timer = window.setInterval(() => {
      if (Date.now() < retryNotBefore.current) return;
      void api.getJob(searchJob.job_id).then(async (fresh) => {
      if (generation !== searchGeneration.current) return;
      resetPollingDelay();
      setSearchJob(fresh);
      if (fresh.status === 'succeeded') { setSearching(false); try { const latest = await api.getSearch(search!.search_id); if (generation === searchGeneration.current) setSearch(latest); } catch (error) { if (generation === searchGeneration.current) setSearchError(error instanceof Error ? error.message : 'Could not load search results.'); } }
      if (fresh.status === 'failed') { setSearching(false); try { const latest = await api.getSearch(search!.search_id); if (generation === searchGeneration.current) setSearch(latest); } catch { if (generation === searchGeneration.current) setSearchError(fresh.error?.message ?? 'Search failed.'); } }
      }).catch((error) => { if (generation === searchGeneration.current) { deferPolling(error); setSearchError(apiErrorMessage(error)); } });
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [deferPolling, resetPollingDelay, searching, searchJob, search]);

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.files?.[0] ?? null;
    setFile(next);
    setUploadError('');
    if (!next) return;
    const validationError = validateVideoSelection(next);
    if (validationError) { setUploadError(validationError); setFile(null); }
  };

  const upload = async (event: FormEvent) => {
    event.preventDefault();
    if (!file || !cameraLabel.trim()) { setUploadError('Choose an MP4 and enter a camera label.'); return; }
    if (cameraLabel.trim().length > 80) { setUploadError('Camera labels can contain up to 80 characters.'); return; }
    setUploading(true);
    setUploadError('');
    try {
      const accepted = await api.uploadVideo(file, cameraLabel.trim());
      setJobs((current) => ({ ...current, [accepted.job.job_id]: accepted.job }));
      setPage(0);
      setFile(null);
      setCameraLabel('');
      await reload(0);
      setSelectedVideoId(accepted.video.video_id);
    } catch (error) { setUploadError(apiErrorMessage(error)); }
    finally { setUploading(false); }
  };

  const startIndex = async (video: Video) => {
    if (busy) return;
    setBusy(true);
    setAppError('');
    try {
      const accepted = video.status === 'failed' ? await api.retryVideo(video.video_id) : await api.indexVideo(video.video_id);
      setJobs((current) => ({ ...current, [accepted.job.job_id]: accepted.job }));
      setVideos((current) => current.map((entry) => entry.video_id === video.video_id ? accepted.video : entry));
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) await reload();
      setAppError(apiErrorMessage(error));
    } finally { setBusy(false); }
  };

  const retry = async (video: Video) => {
    if (busy) return;
    setBusy(true);
    try {
      const accepted = await api.retryVideo(video.video_id);
      setJobs((current) => ({ ...current, [accepted.job.job_id]: accepted.job }));
      setVideos((current) => current.map((entry) => entry.video_id === video.video_id ? accepted.video : entry));
      setAppError('');
    } catch (error) { if (error instanceof ApiError && error.status === 409) await reload(); setAppError(apiErrorMessage(error)); }
    finally { setBusy(false); }
  };

  const submitSearch = async (event: FormEvent) => {
    event.preventDefault();
    setSearchError('');
    const query = searchText.trim();
    if (!query || query.length > 500) { setSearchError('Enter a description between 1 and 500 characters.'); return; }
    if (!selectedVideoIds.length) { setSearchError('Select at least one ready recording.'); return; }
    if (selectedVideoIds.length > 20) { setSearchError('Select no more than 20 recordings.'); return; }
    const start = parseRecordingTime(startTime);
    const end = parseRecordingTime(endTime);
    if ((startTime && start === null) || (endTime && end === null) || Number.isNaN(start) || Number.isNaN(end)) { setSearchError('Enter time in mm:ss format.'); return; }
    if ((start !== null || end !== null) && selectedVideoIds.length !== 1) { setSearchError('Time filters need exactly one selected recording.'); return; }
    const duration = readyVideos.find((video) => video.video_id === selectedVideoIds[0])?.duration_sec;
    if (start !== null && end !== null && (start >= end || (duration != null && end > duration))) { setSearchError('The time range must be positive and within the recording duration.'); return; }
    if ((start === null) !== (end === null)) { setSearchError('Enter both a start and end time.'); return; }
    if (eventTypes.some((kind) => !health?.supported_event_types.includes(kind))) { setSearchError('That event filter is not available from the backend.'); return; }
    const generation = ++searchGeneration.current;
    window.sessionStorage.removeItem('dw_active_search_id');
    setSearching(true);
    setSearch(null);
    setSelectedResult(null);
    setSearchJob(null);
    try {
      const payload = { query, video_ids: selectedVideoIds, limit: 10, ...(start !== null && end !== null ? { time_range: { start_sec: start, end_sec: end } } : {}), ...(eventTypes.length ? { event_types: eventTypes } : {}) };
    const accepted = await api.createSearch(payload);
      if (generation !== searchGeneration.current) return;
      const queued: Search = { search_id: accepted.search_id, job_id: accepted.job.job_id, status: accepted.job.status, query, video_ids: selectedVideoIds, created_at: accepted.job.created_at, warnings: [], results: [], error: null };
      setSearch(queued);
      setSearchJob(accepted.job);
      window.sessionStorage.setItem('dw_active_search_id', accepted.search_id);
    } catch (error) { if (generation === searchGeneration.current) { setSearching(false); setSearchError(apiErrorMessage(error)); } }
  };

  const toggleVideo = (videoId: string) => setSelectedVideoIds((current) => current.includes(videoId) ? current.filter((id) => id !== videoId) : [...current, videoId]);
  const setVideo = (video: Video) => { setSelectedVideoId(video.video_id); setSelectedResult(null); };
  const getJob = (video: Video) => video.active_job_id ? jobs[video.active_job_id] : undefined;
  const reconnectSearch = async () => {
    const searchId = window.sessionStorage.getItem('dw_active_search_id');
    if (!searchId) { (document.getElementById('search-form') as HTMLFormElement | null)?.requestSubmit(); return; }
    const generation = searchGeneration.current;
    try {
      const recovered = await api.getSearch(searchId);
      if (generation !== searchGeneration.current) return;
      setSearch(recovered);
      setSearchError('');
      if (recovered.status === 'queued' || recovered.status === 'running') {
        const recoveredJob = await api.getJob(recovered.job_id);
        if (generation === searchGeneration.current) {
          setSearchJob(recoveredJob);
          setSearching(recoveredJob.status === 'queued' || recoveredJob.status === 'running');
          if (recoveredJob.status === 'succeeded' || recoveredJob.status === 'failed') {
            const latest = await api.getSearch(searchId);
            if (generation === searchGeneration.current) setSearch(latest);
          }
        }
      } else { setSearching(false); setSearchJob(null); }
    } catch (error) { if (generation === searchGeneration.current) setSearchError(apiErrorMessage(error)); }
  };
  const canShowEvents = Boolean(health?.capabilities.temporal_events && health.supported_event_types.length);

  return <main className="app-shell">
    {USE_MOCKS && <div className="mock-ribbon" role="status"><span aria-hidden="true">●</span> MOCK MODE · Sample processing and search data</div>}
    <header className="topbar"><a className="brand" href="#workspace" aria-label="Digital Witness home"><span className="brand-icon">DW</span><span><strong>Digital Witness</strong><small>VIDEO EVIDENCE WORKSPACE</small></span></a><div className="topbar-meta"><span className={`connection-dot ${health ? 'is-online' : ''}`} />{health ? health.mode === 'mock' ? 'Mock service' : 'API connected' : 'Connecting to API'}<span className="topbar-divider" /><span>Contract {health?.contract_version ?? '1.0'}</span></div></header>
    <section className="welcome-row" id="workspace"><div><span className="eyebrow">LOCAL EVIDENCE WORKSPACE</span><h1>Find the moment.<br /><em>Review the evidence.</em></h1><p>Search recordings with natural language, then inspect the original footage and supporting frames.</p></div><div className="welcome-graphic" aria-hidden="true"><div className="graphic-frame"><span className="graphic-time">CAM 04 · 14:32:08</span><span className="graphic-person" /><span className="graphic-scan" /><span className="graphic-corners" /></div><span className="graphic-caption">SOURCE TIMELINE · PRESERVED</span></div></section>
    {appError && <ErrorNotice error={appError} action={<button type="button" className="text-button" onClick={() => void reload()}>Reconnect and refresh</button>} />}

    <div className="workspace-grid">
      <aside className="library-column">
        <section className="panel upload-panel" aria-labelledby="upload-heading"><div className="section-heading"><div><span className="eyebrow">INGEST</span><h2 id="upload-heading">Add recording</h2></div><span className="upload-icon">↑</span></div>
          <form onSubmit={upload}>
            <label className="field-label" htmlFor="camera-label">Camera label</label><input id="camera-label" className="text-input" maxLength={80} value={cameraLabel} onChange={(event) => setCameraLabel(event.target.value)} placeholder="e.g. North entrance" />
            <label className="field-label file-label" htmlFor="recording-file">MP4 video <span>Up to 500 MiB</span></label><input id="recording-file" className="file-input" type="file" accept="video/mp4,.mp4" onChange={handleFile} /><p className="helper-text">MP4 · up to 30 minutes · server validates the video</p>
            {file && <div className="selected-file"><span className="file-symbol">▧</span><span>{file.name}<small>{(file.size / 1024 / 1024).toFixed(1)} MiB selected</small></span><button aria-label="Remove selected file" type="button" onClick={() => setFile(null)}>×</button></div>}
            {uploading && <div className="progress-wrap upload-progress"><div className="progress-label"><span>Sending upload request</span><span>Transfer progress unavailable</span></div><div className="progress-track"><span className="progress-indeterminate" /></div></div>}
            {uploadError && <p className="field-error" role="alert">{uploadError}</p>}
            <button className="button button-primary upload-button" disabled={uploading || !file || !cameraLabel.trim()} type="submit">{uploading ? 'Starting upload…' : 'Upload recording'}<span aria-hidden="true">↗</span></button>
          </form>
        </section>

        <section className="panel recordings-panel" aria-labelledby="recordings-heading"><div className="section-heading recording-heading"><div><span className="eyebrow">YOUR LIBRARY</span><h2 id="recordings-heading">Recordings <span className="count-badge">{total}</span></h2></div><button className="icon-button" aria-label="Refresh recordings" onClick={() => void reload()} disabled={loading}>↻</button></div>
          {loading && <div className="loading-state"><span className="spinner" />Loading recordings…</div>}
          {!loading && !videos.length && <div className="empty-library"><span>◫</span><strong>No recordings yet</strong><p>Upload an MP4 to start your evidence library.</p></div>}
          <div className="recording-list">{videos.map((video) => {
            const job = getJob(video);
            return <article className={`recording-card ${video.video_id === selectedVideoId ? 'is-selected' : ''}`} key={video.video_id}>
              <button className="recording-main" onClick={() => setVideo(video)} aria-pressed={video.video_id === selectedVideoId}>
                <span className="recording-thumb">{video.thumbnail_url ? <img src={video.thumbnail_url} alt="" /> : <span>◷</span>}</span>
                <span className="recording-meta"><strong>{video.camera_label}</strong><small>{video.filename}</small><span className="recording-stats">{formatTime(video.duration_sec)} <span>·</span> {new Date(video.created_at).toLocaleDateString()}</span></span>
              </button>
              <div className="recording-status"><StatusPill status={video.status} />{job && (job.status === 'queued' || job.status === 'running') && <Progress job={job} />}{video.status === 'failed' && <div className="recording-error"><span>{video.error?.message ?? 'Processing failed.'}</span><button className="text-button" disabled={busy} onClick={() => void retry(video)}>{video.playback_url ? 'Retry indexing' : 'Retry preparation'}</button></div>}</div>
            </article>;
          })}</div>
          {total > PAGE_SIZE && <div className="pagination"><button className="button button-quiet" disabled={page === 0 || loading} onClick={() => { const next = page - 1; setPage(next); void reload(next * PAGE_SIZE); }}>Previous</button><span>{page + 1} / {Math.ceil(total / PAGE_SIZE)}</span><button className="button button-quiet" disabled={(page + 1) * PAGE_SIZE >= total || loading} onClick={() => { const next = page + 1; setPage(next); void reload(next * PAGE_SIZE); }}>Next</button></div>}
        </section>
      </aside>

      <div className="main-column">
        {selectedVideo && (selectedVideo.status === 'draft' || (selectedVideo.status === 'failed' && selectedVideo.playback_url)) && <ZoneEditor key={selectedVideo.video_id} video={selectedVideo} busy={busy} onSaved={(updated) => setVideos((current) => current.map((entry) => entry.video_id === updated.video_id ? updated : entry))} onStart={startIndex} />}
        {selectedVideo && (selectedVideo.status === 'preparing' || selectedVideo.status === 'indexing') && <section className="panel process-panel"><div className="section-heading"><div><span className="eyebrow">PROCESSING RECORDING</span><h2>{selectedVideo.camera_label}</h2><p>{selectedVideo.status === 'preparing' ? 'Preparing a browser playable preview.' : 'Building the searchable recording index.'}</p></div><StatusPill status={selectedVideo.status} /></div>{selectedVideo.active_job_id && jobs[selectedVideo.active_job_id] ? <Progress job={jobs[selectedVideo.active_job_id]} /> : <div className="progress-wrap"><div className="progress-label"><span>Waiting for backend status</span><span>Progress unavailable</span></div><div className="progress-track"><span className="progress-indeterminate" /></div></div>}</section>}
        {selectedVideo?.status === 'ready' && <section className="panel ready-preview"><div><span className="eyebrow">RECORDING READY</span><h2>{selectedVideo.camera_label}</h2><p>{selectedVideo.filename} · {formatTime(selectedVideo.duration_sec)} · {selectedVideo.width ?? '—'}×{selectedVideo.height ?? '—'}</p></div>{selectedVideo.playback_url && <video controls preload="metadata" src={selectedVideo.playback_url} aria-label={`Preview of ${selectedVideo.camera_label}`} />}</section>}

        <section className="panel search-panel" aria-labelledby="search-heading"><div className="section-heading"><div><span className="eyebrow">SEMANTIC SEARCH</span><h2 id="search-heading">Describe a moment</h2><p>Searches return candidate moments for review, not confirmed events.</p></div><span className="search-mark">⌕</span></div>
          <form id="search-form" onSubmit={submitSearch}>
            <label className="field-label" htmlFor="search-query">What are you looking for?</label><textarea id="search-query" className="text-input query-input" maxLength={500} value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="A person carrying a bag near the entrance…" />
            <div className="search-controls"><fieldset className="video-select"><legend className="field-label">Ready recordings</legend>{readyVideos.length ? readyVideos.map((video) => <label key={video.video_id} className="check-label"><input type="checkbox" checked={selectedVideoIds.includes(video.video_id)} onChange={() => toggleVideo(video.video_id)} />{video.camera_label}</label>) : <p className="helper-text">No ready recordings yet. Index one to enable search.</p>}</fieldset>
              <div className="time-filter"><span className="field-label">Optional time range <small>one recording only</small></span><div className="time-fields"><label>From<input className="text-input" inputMode="numeric" placeholder="00:00" aria-label="Start time in minutes and seconds" value={startTime} onChange={(event) => setStartTime(event.target.value)} /></label><span>—</span><label>To<input className="text-input" inputMode="numeric" placeholder="02:30" aria-label="End time in minutes and seconds" value={endTime} onChange={(event) => setEndTime(event.target.value)} /></label></div><span className="helper-text">Recording time in mm:ss</span></div>
            </div>
            {canShowEvents && <fieldset className="event-filter"><legend className="field-label">Event types supported by this backend</legend>{health?.supported_event_types.map((kind) => <label key={kind} className="check-label"><input type="checkbox" checked={eventTypes.includes(kind)} onChange={() => setEventTypes((current) => current.includes(kind) ? current.filter((item) => item !== kind) : [...current, kind])} />{eventNames[kind]}</label>)}</fieldset>}
            {!health?.capabilities.semantic_search && health && <p className="capability-note"><span>i</span> Semantic search is unavailable in this backend.</p>}
            {!canShowEvents && health?.capabilities.temporal_events === false && <p className="capability-note"><span>i</span> Event filters are unavailable in this backend. Semantic search remains available.</p>}
            {searchError && <p className="field-error" role="alert">{searchError}</p>}
            <div className="search-submit-row"><span className="helper-text">Top 10 candidates · original timestamps</span><button className="button button-primary" type="submit" disabled={searching || !readyVideos.length || !health?.capabilities.semantic_search}>{searching ? 'Searching…' : 'Search recordings'}<span aria-hidden="true">↗</span></button></div>
          </form>
        </section>

        <ChatPanel videos={readyVideos.filter((video) => selectedVideoIds.includes(video.video_id))} available={Boolean(health?.capabilities.chat)} onReview={(retrieved, result) => {
          searchGeneration.current++;
          setSearching(false); setSearchJob(null); setSearchError(''); setSearch(retrieved); setSelectedResult(result);
          window.sessionStorage.setItem('dw_active_search_id', retrieved.search_id);
          document.getElementById('results-heading')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }} />

        <section className="results-section" aria-labelledby="results-heading"><div className="results-title"><div><span className="eyebrow">REVIEW</span><h2 id="results-heading">Search results</h2></div>{search?.status === 'succeeded' && <span className="result-count">{search.results.length} {search.results.length === 1 ? 'candidate' : 'candidates'}</span>}</div>
          {searching && <div className="panel search-progress"><span className="spinner" /><div><strong>{searchJob?.stage === 'verifying' ? 'Checking evidence frames' : searchJob?.stage === 'retrieving' ? 'Retrieving candidate moments' : 'Search queued'}</strong><p>{searchError || (searchJob ? `${searchJob.progress_pct}% estimated progress` : 'Waiting for status from the backend.')}</p>{searchError && <button className="text-button" onClick={() => void reconnectSearch()}>Reconnect or try again</button>}</div>{searchJob && <Progress job={searchJob} />}</div>}
          {!searching && searchError && <ErrorNotice error={searchError} action={<button className="text-button" onClick={() => void reconnectSearch()}>Reconnect or try again</button>} />}
          {!searching && search?.status === 'failed' && <ErrorNotice error={search.error?.message ?? 'Search failed. Submit a new search to try again.'} action={<button className="text-button" onClick={() => (document.getElementById('search-form') as HTMLFormElement | null)?.requestSubmit()}>Try a new search</button>} />}
          {!searching && search?.status === 'succeeded' && search.warnings.length > 0 && <div className="warning-list" role="status">{search.warnings.map((warning) => <p key={warning.code}><span>!</span>{warning.message}</p>)}</div>}
          {!searching && search?.status === 'succeeded' && search.results.length === 0 && <div className="panel empty-results"><span className="empty-icon">⌕</span><h3>No matching moments found</h3><p>No candidates passed this search. This does not prove that an event never happened.</p></div>}
          {!searching && search?.status === 'succeeded' && search.results.length > 0 && <div className="results-layout"><div className="result-list">{search.results.map((result, index) => <article className={`result-card ${selectedResult?.result_id === result.result_id ? 'is-active' : ''}`} key={result.result_id}>
            <button className="result-select" onClick={() => setSelectedResult(result)} aria-pressed={selectedResult?.result_id === result.result_id}><img src={result.thumbnail_url} alt={`Candidate frame from ${result.camera_label}`} /><span className="result-index">{String(index + 1).padStart(2, '0')}</span><span className="result-interval">{formatTime(result.start_sec)}–{formatTime(result.end_sec)}</span><span className="result-main"><strong>{result.camera_label}</strong><span>{result.summary}</span></span></button>
            <div className="verification-row"><span className={`verification-mark verification-${result.verification.status}`}>{result.verification.status === 'supported' ? '✓' : result.verification.status === 'contradicted' ? '×' : '·'}</span><div><strong>{verificationLabel(result.verification.status, result.verification.basis)}</strong><p>{result.verification.reason}</p></div></div>
            <details className="result-details"><summary>Evidence & retrieval details</summary><p><strong>Basis:</strong> {result.verification.basis.replaceAll('_', ' ')}</p><p><strong>Reason:</strong> {result.verification.reason}</p><p><strong>Retrieval score:</strong> {result.retrieval_score.toFixed(3)} <span className="muted-copy">(cosine similarity, not accuracy)</span></p>{result.evidence.map((frame) => <div className="check-detail" key={`${frame.timestamp_sec}-${frame.image_url}`}><strong>Frame {formatTime(frame.timestamp_sec)} · {frame.quality}</strong>{frame.checks.map((check) => <p key={check.check_id}>{check.question} — {check.answer}{check.probability_yes !== null ? ` · probability_yes ${check.probability_yes.toFixed(2)}` : ''}</p>)}</div>)}</details>
          </article>)}</div><EvidencePlayer result={selectedResult ?? search.results[0]} /></div>}
          {!search && !searching && <div className="panel results-placeholder"><span className="empty-icon">⌕</span><h3>Search your recordings</h3><p>Results and frame evidence will appear here after a search.</p></div>}
        </section>
      </div>
    </div>
    <footer className="site-footer"><span>Digital Witness <b>·</b> Local evidence review</span><span>Frame checks support narrow visual claims only.</span></footer>
  </main>;
}
