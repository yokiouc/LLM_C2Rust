"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/shared/status-badge";
import type { PatchesResponse } from "@/lib/api/types";

export function PatchDiff({ data }: { data: PatchesResponse }) {
  if (!data.patches.length) {
    return <p className="py-4 text-center text-sm text-muted-foreground">No patches generated</p>;
  }

  return (
    <div className="space-y-4">
      {data.patches.map((patch, idx) => (
        <Card key={patch.patch_id}>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              Patch #{idx + 1}
              <StatusBadge status={patch.status} />
              <span className="font-mono text-xs text-muted-foreground">{patch.file_path}</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs leading-relaxed">
              {patch.unified_diff.split("\n").map((line, i) => (
                <DiffLine key={i} line={line} />
              ))}
            </pre>
            {patch.error_msg && (
              <p className="mt-2 text-xs text-destructive">{patch.error_msg}</p>
            )}
          </CardContent>
        </Card>
      ))}

      {data.rollbacks.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Rollback History ({data.rollbacks.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1 text-xs">
              {data.rollbacks.map((rb, i) => (
                <div key={i} className="flex gap-2 text-muted-foreground">
                  <span className="font-mono">{String((rb as Record<string, unknown>).rollback_reason || "unknown")}</span>
                  <span>{String((rb as Record<string, unknown>).created_at || "")}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function DiffLine({ line }: { line: string }) {
  let className = "whitespace-pre font-mono";
  if (line.startsWith("+") && !line.startsWith("+++")) {
    className += " text-green-700 bg-green-50 dark:text-green-400 dark:bg-green-950";
  } else if (line.startsWith("-") && !line.startsWith("---")) {
    className += " text-red-700 bg-red-50 dark:text-red-400 dark:bg-red-950";
  } else if (line.startsWith("@@")) {
    className += " text-blue-600 dark:text-blue-400";
  } else if (line.startsWith("---") || line.startsWith("+++")) {
    className += " font-semibold";
  }
  return <div className={className}>{line || "\u00a0"}</div>;
}
