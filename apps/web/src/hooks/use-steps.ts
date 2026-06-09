"use client";

import { useQuery } from "@tanstack/react-query";

interface StepEntry {
  step_id: string;
  step_name: string;
  ok: boolean;
  error_msg: string | null;
  iteration: string | null;
  elapsed_ms: string | null;
  created_at: string;
}

interface StepsResponse {
  run_id: string;
  steps: StepEntry[];
  count: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export function useRunSteps(runId: string) {
  return useQuery<StepsResponse>({
    queryKey: ["run-steps", runId],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/runs/${runId}/steps`);
      if (!res.ok) throw new Error(`Failed: ${res.status}`);
      return res.json();
    },
    enabled: !!runId,
    retry: 1,
  });
}

export type { StepEntry, StepsResponse };
