import { formatMessage, messages } from '../messages';
import { ErrorCode } from './codes';
import { ApiError, networkError } from './errors';
import type { ApiEnvelope } from './types';

function isEnvelope(value: unknown): value is ApiEnvelope<unknown> {
  if (!value || typeof value !== 'object') return false;
  const body = value as Partial<ApiEnvelope<unknown>>;
  if (typeof body.ok !== 'boolean' || !('data' in body) || !body.meta || typeof body.meta.request_id !== 'string') return false;
  if (body.ok) return body.error === null;
  return !!body.error && typeof body.error.code === 'string' && typeof body.error.message === 'string'
    && Array.isArray(body.error.details) && body.error.details.every(detail => detail && typeof detail === 'object'
      && (detail.field === undefined || typeof detail.field === 'string')
      && (detail.code === undefined || typeof detail.code === 'string'));
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers({ 'Content-Type': 'application/json', 'X-Nodekit-Request': '1' });
  new Headers(init?.headers).forEach((value, key) => headers.set(key, value));
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw networkError();
  }
  const body: unknown = await response.json().catch(() => null);
  if (!isEnvelope(body)) {
    throw new ApiError(messages.error.invalidResponse, ErrorCode.InvalidResponse, response.status);
  }
  if (!response.ok || !body.ok) {
    throw new ApiError(body.error?.message ?? formatMessage(messages.error.http, { status: response.status }),
      body.error?.code ?? ErrorCode.HttpError, response.status, body.error?.details ?? [], body.meta.request_id);
  }
  return body.data as T;
}
