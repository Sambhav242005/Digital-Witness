import type { ApiErrorBody } from './types';

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  requestId: string | null;
  retryAfterSec: number | null;

  constructor(input: { status: number; error: ApiErrorBody; requestId?: string | null; retryAfterSec?: number | null }) {
    super(input.error.message);
    this.name = 'ApiError';
    this.status = input.status;
    this.code = input.error.code;
    this.details = input.error.details;
    this.requestId = input.requestId ?? null;
    this.retryAfterSec = input.retryAfterSec ?? null;
  }
}

export async function parseApiError(response: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  const envelope = body && typeof body === 'object' ? body as Record<string, unknown> : {};
  const rawError = envelope.error && typeof envelope.error === 'object' ? envelope.error as Record<string, unknown> : {};
  const error: ApiErrorBody = {
    code: typeof rawError.code === 'string' ? rawError.code : 'HTTP_ERROR',
    message: typeof rawError.message === 'string' ? rawError.message : `Request failed (${response.status}).`,
    details: rawError.details && typeof rawError.details === 'object' ? rawError.details as Record<string, unknown> : {},
  };
  const retryHeader = response.headers.get('Retry-After');
  const retryAfterSec = retryHeader && Number.isFinite(Number(retryHeader)) ? Number(retryHeader) : null;
  return new ApiError({ status: response.status, error, requestId: typeof envelope.request_id === 'string' ? envelope.request_id : null, retryAfterSec });
}
