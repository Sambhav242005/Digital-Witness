import type { Point } from './types';

export function parseRecordingTime(value: string): number | null {
  if (!value.trim()) return null;
  const match = value.trim().match(/^(\d{1,6}):([0-5]\d)$/);
  if (!match) return Number.NaN;
  return Number(match[1]) * 60 + Number(match[2]);
}

export function validateVideoSelection(file: Pick<File, 'name' | 'type' | 'size'>): string | null {
  if (!file.name.toLowerCase().endsWith('.mp4') && file.type !== 'video/mp4') return 'Choose an MP4 video file.';
  if (file.size > 500 * 1024 * 1024) return 'This file exceeds the 500 MiB upload limit.';
  return null;
}

export function polygonError(points: Point[]): string | null {
  if (points.length < 3 || points.length > 12) return 'An entrance needs 3 to 12 points.';
  if (points.some((point, index) => points.some((other, otherIndex) => index !== otherIndex && point.x === other.x && point.y === other.y))) return 'Each point must be unique.';
  const area = points.reduce((sum, point, index) => { const next = points[(index + 1) % points.length]; return sum + point.x * next.y - next.x * point.y; }, 0);
  if (Math.abs(area) < 0.00001) return 'The entrance shape needs a non-zero area.';
  const orientation = (firstPoint: Point, secondPoint: Point, thirdPoint: Point) => (secondPoint.x - firstPoint.x) * (thirdPoint.y - firstPoint.y) - (secondPoint.y - firstPoint.y) * (thirdPoint.x - firstPoint.x);
  const intersects = (firstPoint: Point, secondPoint: Point, thirdPoint: Point, fourthPoint: Point) => orientation(firstPoint, secondPoint, thirdPoint) * orientation(firstPoint, secondPoint, fourthPoint) < 0 && orientation(thirdPoint, fourthPoint, firstPoint) * orientation(thirdPoint, fourthPoint, secondPoint) < 0;
  for (let first = 0; first < points.length; first += 1) {
    const firstNext = (first + 1) % points.length;
    for (let second = first + 1; second < points.length; second += 1) {
      const secondNext = (second + 1) % points.length;
      if (first === second || firstNext === second || secondNext === first) continue;
      if (intersects(points[first], points[firstNext], points[second], points[secondNext])) return 'The entrance shape cannot cross itself.';
    }
  }
  return null;
}

export function verificationLabel(status: string, basis: string): string {
  if (status === 'supported' && basis === 'frame_checks') return 'Frame check supported.';
  if (status === 'supported' && basis === 'temporal_rule') return 'Temporal rule supported.';
  if (status === 'uncertain') return 'Needs review.';
  if (status === 'contradicted') return 'Check did not support this candidate.';
  return 'Not checked.';
}
