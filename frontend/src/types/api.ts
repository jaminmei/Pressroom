export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface ApiErrorResponse {
  error: ApiError;
  request_id?: string;
}

export interface ApiResponse<T> {
  data: T;
  request_id?: string;
}
