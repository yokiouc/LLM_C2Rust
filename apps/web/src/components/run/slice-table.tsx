"use client";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { RepairSlice } from "@/lib/api/types";

export function SliceTable({ slices }: { slices: RepairSlice[] }) {
  if (!slices.length) {
    return <p className="py-4 text-center text-sm text-muted-foreground">No slices found</p>;
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[180px]">File</TableHead>
            <TableHead>Symbol</TableHead>
            <TableHead className="text-center">Range</TableHead>
            <TableHead className="text-center">Anchor</TableHead>
            <TableHead>Constraints</TableHead>
            <TableHead>Unsafe Ops</TableHead>
            <TableHead>Forbidden</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {slices.map((s) => (
            <TableRow key={s.id}>
              <TableCell className="font-mono text-xs">{s.file_path}</TableCell>
              <TableCell className="font-mono text-xs">{s.symbol || "-"}</TableCell>
              <TableCell className="text-center font-mono text-xs">
                {s.slice_start}-{s.slice_end}
              </TableCell>
              <TableCell className="text-center font-mono text-xs">{s.anchor_line ?? "-"}</TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {s.keep_signature && <Badge variant="outline" className="text-xs">keep_sig</Badge>}
                  {s.no_global_rename && <Badge variant="outline" className="text-xs">no_rename</Badge>}
                  {s.min_patch && <Badge variant="outline" className="text-xs">min_patch</Badge>}
                </div>
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {s.related_unsafe_ops.slice(0, 3).map((op) => (
                    <Badge key={op} variant="secondary" className="font-mono text-xs">{op}</Badge>
                  ))}
                  {s.related_unsafe_ops.length > 3 && (
                    <Badge variant="secondary" className="text-xs">+{s.related_unsafe_ops.length - 3}</Badge>
                  )}
                </div>
              </TableCell>
              <TableCell className="font-mono text-xs">
                {s.forbidden_regions.length > 0
                  ? s.forbidden_regions.map((f) => `L${f.start}-${f.end}`).join(", ")
                  : "-"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
