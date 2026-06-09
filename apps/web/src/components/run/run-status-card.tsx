"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/shared/status-badge";
import type { RunStatus } from "@/lib/api/types";

export function RunStatusCard({ data }: { data: RunStatus }) {
  const duration = data.total_ms ? `${(data.total_ms / 1000).toFixed(1)}s` : "-";
  const lastScore = data.progress_score_history?.length
    ? data.progress_score_history[data.progress_score_history.length - 1]
    : null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          Run Status
          <StatusBadge status={data.final_status || data.status} />
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm md:grid-cols-4">
          <Stat label="Run ID" value={data.run_id.slice(0, 8)} mono />
          <Stat label="Iterations" value={data.iteration_count ?? 0} />
          <Stat label="Rollbacks" value={data.rollback_count ?? 0} />
          <Stat label="Duration" value={duration} />
          <Stat label="Stop Reason" value={data.final_stop_reason || "-"} />
          <Stat label="Progress Score" value={lastScore !== null ? lastScore.toFixed(1) : "-"} />
          <Stat label="Created" value={new Date(data.created_at).toLocaleString()} />
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value, mono }: { label: string; value: string | number; mono?: boolean }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`font-medium ${mono ? "font-mono text-xs" : ""}`}>{String(value)}</p>
    </div>
  );
}
