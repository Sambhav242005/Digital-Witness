import { describe, expect, it } from 'vitest';
import { parseRecordingTime, polygonError, validateVideoSelection, verificationLabel } from './validation';
import { fixtureErrors, fixtureJobs, fixtureSearches, fixtureVideos } from './fixtures';
import { parseApiError } from './errors';

describe('frontend contract validation', () => {
  it('converts mm:ss to recording-relative seconds and rejects malformed times', () => {
    expect(parseRecordingTime('02:15')).toBe(135);
    expect(parseRecordingTime('2:60')).toBeNaN();
    expect(parseRecordingTime('')).toBeNull();
  });

  it('rejects unsupported and oversized uploads', () => {
    expect(validateVideoSelection({ name: 'clip.mov', type: 'video/quicktime', size: 100 })).toContain('MP4');
    expect(validateVideoSelection({ name: 'clip.mp4', type: 'video/mp4', size: 501 * 1024 * 1024 })).toContain('500 MiB');
    expect(validateVideoSelection({ name: 'clip.mp4', type: 'video/mp4', size: 100 })).toBeNull();
  });

  it('validates normalized entrance polygons', () => {
    expect(polygonError([{ x: 0, y: 0 }, { x: 1, y: 0 }])).toContain('3 to 12');
    expect(polygonError([{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }])).toBeNull();
    expect(polygonError([{ x: 0, y: 0 }, { x: 0, y: 0 }, { x: 1, y: 1 }])).toContain('unique');
  });

  it('uses the contract verification labels', () => {
    expect(verificationLabel('supported', 'frame_checks')).toBe('Frame check supported.');
    expect(verificationLabel('supported', 'temporal_rule')).toBe('Temporal rule supported.');
    expect(verificationLabel('uncertain', 'none')).toBe('Needs review.');
    expect(verificationLabel('contradicted', 'none')).toBe('Check did not support this candidate.');
    expect(verificationLabel('not_checked', 'none')).toBe('Not checked.');
  });

  it('provides typed lifecycle, search, and error fixtures', () => {
    expect(fixtureVideos.map((video) => video.status)).toEqual(['ready', 'draft', 'preparing', 'indexing', 'failed', 'failed']);
    expect(fixtureJobs.map((job) => job.status)).toEqual(['queued', 'running', 'succeeded', 'failed']);
    expect(fixtureSearches.map((search) => search.search_id)).toEqual(expect.arrayContaining(['search_demo_populated', 'search_demo_empty', 'search_demo_degraded', 'search_demo_failed']));
    expect([fixtureErrors.conflict.status, fixtureErrors.validation.status, fixtureErrors.unavailable.status]).toEqual([409, 422, 503]);
  });

  it('parses the shared error envelope and Retry-After header', async () => {
    const response = new Response(JSON.stringify({ error: { code: 'QUEUE_FULL', message: 'Queue is full.', details: { queued: 20 } }, request_id: 'req_123' }), { status: 429, headers: { 'Retry-After': '7', 'Content-Type': 'application/json' } });
    const error = await parseApiError(response);
    expect(error.code).toBe('QUEUE_FULL');
    expect(error.requestId).toBe('req_123');
    expect(error.retryAfterSec).toBe(7);
  });
});
