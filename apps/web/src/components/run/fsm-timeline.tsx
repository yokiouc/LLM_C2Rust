"use client";

import { Badge } from "@/components/ui/badge";
import type { StepEntry } from "@/hooks/use-steps";

const STATE_COLORS: Record<string, string> = {
  INIT: "bg-gray-200 text-gray-800",
  PRECHECK: "bg-gray-200 text-gray-800",
  HOTSPOT_DISCOVERY: "bg-purple-100 text-purple-800",
  SLICE_SELECT: "bg-purple-100 text-purple-800",
  RETRIEVE_EVIDENCE: "bg-blue-100 text-blue-800",
  RETRIEVE: "bg-blue-100 text-blue-800",
  BUILD_PROMPT: "bg-blue-100 text-blue-800",
  GENERATE_PATCH: "bg-indigo-100 text-indigo-800",
  GENERATE: "bg-indigo-100 text-indigo-800",
  VALIDATE_PATCH: "bg-indigo-100 text-indigo-800",
  APPLY_PATCH: "bg-yellow-100 text-yellow-800",
  APPLY: "bg-yellow-100 text-yellow-800",
  RUN_BUILD: "bg-orange-100 text-orange-800",
  RUN_TEST: "bg-orange-100 text-orange-800",
  RUN_LINT: "bg-orange-100 text-orange-800",
  EXECUTE: "bg-orange-100 text-orange-800",
  DIAGNOSE: "bg-red-100 text-red-800",
  SCORE_PROGRESS: "bg-teal-100 text-teal-800",
  ROLLBACK: "bg-red-100 text-red-800",
  SUCCESS: "bg-green-200 text-green-800",
  STOP: "bg-green-200 text-green-800",
  STOP_NO_PROGRESS: "bg-yellow-200 text-yellow-800",
  STOP_MAX_ITERS: "bg-yellow-200 text-yellow-800",
  STOP_HARD_ERROR: "bg-red-200 text-red-800",
  FAILED: "bg-red-200 text-red-800",
};

export function FSMTimeline({ steps }: { steps: StepEntry[] }) {
  if (!steps.length) {
    return <p className="py-4 text-center text-sm text-muted-foreground">No steps recorded</p>;
  }

  return (
    <div className="relative space-y-0">
      {steps.map((step, idx) => {
        const color = STATE_COLORS[step.step_name] || "bg-gray-100 text-gray-700";
        const elapsed = step.elapsed_ms ? `${parseInt(step.elapsed_ms)}ms` : "";
        const isLast = idx === steps.length - 1;

        return (
          <div key={step.step_id} className="flex items-start gap-3">
            {/* Timeline connector */}
            <div className="flex flex-col items-center">
              <div className={`h-3 w-3 rounded-full ${step.ok ? "bg-green-500" : "bg-red-500"} ring-2 ring-background`} />
              {!isLast && <div className="h-8 w-px bg-border" />}
            </div>

            {/* Step content */}
            <div className="flex flex-1 items-center gap-2 pb-2">
              <Badge className={`${color} text-xs font-mono`}>{step.step_name}</Badge>
              {step.iteration && (
                <span className="text-xs text-muted-foreground">iter {step.iteration}</span>
              )}
              {elapsed && (
                <span className="font-mono text-xs text-muted-foreground">{elapsed}</span>
              )}
              {step.error_msg && (
                <span className="truncate text-xs text-destructive" title={step.error_msg}>
                  {step.error_msg.slice(0, 60)}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
