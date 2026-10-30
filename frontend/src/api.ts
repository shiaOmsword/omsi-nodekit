// Compatibility facade for existing callers; application DTOs stay outside framework.
export { api, ApiError, ErrorCode, getErrorMessage } from './framework/api';
export type { ApiEnvelope, ApiErrorDetail } from './framework/api';
export type { Action, Backup, Event, Job, JobDetail, NodeRecord, NodeSummary, Plan } from './types';
