"use client";

import { StatusBadge } from "@/components/shared/status-badge";
import type { ValidationResponse } from "@/lib/api/types";

const STAGE_ORDER = ["build", "test", "clippy", "fmt"];
const STAGE_LABELS: Record<string, string> = {
  build: "Build",
  test: "Test",
  clippy: "Clippy",
  fmt: "Format",
};

export function ValidationTimeline({ data }: { data: ValidationResponse }) {
  const summary = data.summary;
  const hasAny = Object.values(summary).some((v) => v !== null);

  if (!hasAny && !data.results.length) {
    return <p className="py-4 text-center text-sm text-muted-foreground">No validation results</p>;
  }

  return (
    <div className="flex gap-2">
      {STAGE_ORDER.map((stage) => {
        const result = summary[stage as keyof typeof summary];
        return (
          <div
            key={stage}
            className="flex flex-1 flex-col items-center rounded-lg border p-3"
          >
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              {STAGE_LABELS[stage] || stage}
            </p>
            <StatusBadge status={result?.status ?? "skip"} />
            {result?.duration_ms !== undefined && result.duration_ms !== null && (
              <p className="mt-1 font-mono text-xs text-muted-foreground">
                {result.duration_ms >= 1000
                  ? `${(result.duration_ms / 1000).toFixed(1)}s`
                  : `${result.duration_ms}ms`}
              </p>
            )}
            {result && result.issue_count > 0 && (
              <p className="mt-0.5 text-xs text-red-600">{result.issue_count} issues</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
