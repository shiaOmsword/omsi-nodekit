export interface ApiErrorDetail { field?: string; code?: string; [key: string]: unknown }
export interface ApiEnvelope<T> {
  ok: boolean;
  data: T | null;
  error: { code: string; message: string; details: ApiErrorDetail[] } | null;
  meta: { request_id: string };
}
