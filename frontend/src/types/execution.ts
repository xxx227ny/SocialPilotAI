export type ExecutionJobStatus =
  | "QUEUED"
  | "RUNNING"
  | "PAUSED"
  | "SUCCEEDED"
  | "FAILED"
  | "SUBMIT_UNKNOWN"
  | "CANCELLED";

export interface ExecutionJob {
  id: number;
  job_type: string;
  source_type: string;
  source_id: number;
  input_digest: string;
  input_payload: Record<string, unknown>;
  status: ExecutionJobStatus;
  attempt_count: number;
  max_attempts: number;
  result_entity_type: string | null;
  result_entity_id: number | null;
  safe_error_code: string | null;
  uncertain: boolean;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface ExecutionJobCreateResult {
  job: ExecutionJob;
  reused: boolean;
}
