/** Unified API client for the C2Rust Repair System backend. */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    throw new ApiError(res.status, `API error: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// --- Runs ---

import type {
  RunSummary,
  RunStatus,
  HotspotsResponse,
  SlicesResponse,
  ValidationResponse,
  MetricsResponse,
  PatchesResponse,
  CompareResponse,
} from "./types";

export async function listRuns(limit = 50, offset = 0): Promise<RunSummary[]> {
  return fetchJson<RunSummary[]>(`/runs?limit=${limit}&offset=${offset}`);
}

export async function getRunStatus(runId: string): Promise<RunStatus> {
  return fetchJson<RunStatus>(`/runs/${runId}/status`);
}

export async function getRunDetail(runId: string): Promise<Record<string, unknown>> {
  return fetchJson<Record<string, unknown>>(`/runs/${runId}`);
}

export async function getRunHotspots(runId: string): Promise<HotspotsResponse> {
  return fetchJson<HotspotsResponse>(`/runs/${runId}/hotspots`);
}

export async function getRunSlices(runId: string): Promise<SlicesResponse> {
  return fetchJson<SlicesResponse>(`/runs/${runId}/slices`);
}

export async function getRunValidation(runId: string): Promise<ValidationResponse> {
  return fetchJson<ValidationResponse>(`/runs/${runId}/validation`);
}

export async function getRunMetrics(runId: string): Promise<MetricsResponse> {
  return fetchJson<MetricsResponse>(`/runs/${runId}/metrics`);
}

export async function getRunPatches(runId: string): Promise<PatchesResponse> {
  return fetchJson<PatchesResponse>(`/runs/${runId}/patches`);
}

// --- Compare ---

export async function getCompare(
  baselineRunId: string,
  enhancedRunId: string,
): Promise<CompareResponse> {
  return fetchJson<CompareResponse>(
    `/compare?baseline_run_id=${baselineRunId}&enhanced_run_id=${enhancedRunId}`,
  );
}

export { ApiError };
