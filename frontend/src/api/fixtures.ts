import demoData from '../../demo.json';
import type { ApiErrorBody, Job, Search, Video } from './types';

type DemoData = {
  videos: Video[];
  jobs: Job[];
  searches: Search[];
  errors: Record<'conflict' | 'validation' | 'unavailable', { status: number; error: ApiErrorBody }>;
};

const demo = demoData as unknown as DemoData;

export const fixtureVideos = demo.videos;
export const fixtureJobs = demo.jobs;
export const fixtureSearches = demo.searches;
export const fixtureErrors = demo.errors;
