import { messages } from '../messages';
import { ErrorCode } from './codes';
import type { ApiErrorDetail } from './types';

export class ApiError extends Error {
  constructor(message: string, public readonly code: string, public readonly status: number,
    public readonly details: ApiErrorDetail[] = [], public readonly requestId = '') {
    const fields = details.map(item => item.field).filter(Boolean).join(', ');
    super(fields ? `${message}: ${fields}` : message);
    this.name = 'ApiError';
  }
}

export function getErrorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : messages.error.unknown;
}

export function networkError(): ApiError {
  return new ApiError(messages.error.network, ErrorCode.NetworkError, 0);
}
