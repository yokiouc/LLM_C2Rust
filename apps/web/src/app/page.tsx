"use client";

import Link from "next/link";
import { useRuns } from "@/hooks/use-runs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge, ModeBadge } from "@/components/shared/status-badge";
import { LoadingState, ErrorState, EmptyState } from "@/components/shared/empty-state";

export default function DashboardPage() {
  const { data: runs, isLoading, error } = useRuns();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <p className="text-sm text-muted-foreground">Repair agent runs overview</p>
      </div>

      {runs && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
          <SummaryCard title="Total Runs" value={runs.length} />
          <SummaryCard title="Successful" value={runs.filter((r) => r.final_status === "OK").length} />
          <SummaryCard title="Failed" value={runs.filter((r) => r.final_status === "FAILED").length} />
          <SummaryCard title="Enhanced" value={runs.filter((r) => r.mode === "enhanced").length} />
        </div>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Recent Runs</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading && <LoadingState />}
          {error && <ErrorState message={error instanceof Error ? error.message : "Failed to load runs"} />}
          {runs && runs.length === 0 && <EmptyState message="No runs yet. Start a repair agent run via the API." />}
          {runs && runs.length > 0 && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Run ID</TableHead>
                    <TableHead>Mode</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Stop Reason</TableHead>
                    <TableHead className="text-center">Iters</TableHead>
                    <TableHead className="text-center">Rollbacks</TableHead>
                    <TableHead className="text-right">Duration</TableHead>
                    <TableHead>Created</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.map((run) => (
                    <TableRow key={run.run_id}>
                      <TableCell>
                        <Link href={`/runs/${run.run_id}`} className="font-mono text-xs text-blue-600 hover:underline">
                          {run.run_id.slice(0, 8)}...
                        </Link>
                      </TableCell>
                      <TableCell><ModeBadge mode={typeof run.mode === "string" ? run.mode : null} /></TableCell>
                      <TableCell><StatusBadge status={typeof run.final_status === "string" ? run.final_status : run.status} /></TableCell>
                      <TableCell className="text-xs">{typeof run.final_stop_reason === "string" ? run.final_stop_reason : "-"}</TableCell>
                      <TableCell className="text-center font-mono text-xs">{run.iteration_count ?? "-"}</TableCell>
                      <TableCell className="text-center font-mono text-xs">{run.rollback_count ?? "-"}</TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {typeof run.total_ms === "number" ? `${(run.total_ms / 1000).toFixed(1)}s` : "-"}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {new Date(run.created_at).toLocaleString()}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SummaryCard({ title, value }: { title: string; value: number }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <p className="text-xs text-muted-foreground">{title}</p>
        <p className="text-2xl font-bold">{value}</p>
      </CardContent>
    </Card>
  );
}
