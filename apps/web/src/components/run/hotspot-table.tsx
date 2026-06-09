"use client";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RiskBadge } from "@/components/shared/status-badge";
import { Badge } from "@/components/ui/badge";
import type { Hotspot } from "@/lib/api/types";

export function HotspotTable({ hotspots }: { hotspots: Hotspot[] }) {
  if (!hotspots.length) {
    return <p className="py-4 text-center text-sm text-muted-foreground">No hotspots found</p>;
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[180px]">File</TableHead>
            <TableHead>Symbol</TableHead>
            <TableHead>Kind</TableHead>
            <TableHead className="text-center">Lines</TableHead>
            <TableHead className="text-center">Risk</TableHead>
            <TableHead>Tags</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {hotspots.map((h) => (
            <TableRow key={h.id}>
              <TableCell className="font-mono text-xs">{h.file_path}</TableCell>
              <TableCell className="font-mono text-xs">{h.symbol || "-"}</TableCell>
              <TableCell>
                <Badge variant="outline" className="text-xs">{h.hotspot_kind}</Badge>
              </TableCell>
              <TableCell className="text-center font-mono text-xs">
                {h.start_line}-{h.end_line}
              </TableCell>
              <TableCell className="text-center">
                <div className="flex items-center justify-center gap-1">
                  <span className="font-mono text-xs">{h.risk_score}</span>
                  <RiskBadge level={h.risk_level} />
                </div>
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {h.risk_tags.map((t) => (
                    <Badge key={t} variant="secondary" className="text-xs">{t}</Badge>
                  ))}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
