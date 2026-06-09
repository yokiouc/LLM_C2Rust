"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { MetricsResponse } from "@/lib/api/types";

export function MetricsCard({ data }: { data: MetricsResponse }) {
  const eng = data.engineering as Record<string, number>;
  const ev = data.evaluation as Record<string, unknown>;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Metrics</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Section title="Engineering">
          <MetricRow label="Total" value={fmtMs(eng.total_ms)} />
          <MetricRow label="Retrieve" value={fmtMs(eng.retrieve_ms)} />
          <MetricRow label="Generate" value={fmtMs(eng.generate_ms)} />
          <MetricRow label="Build" value={fmtMs(eng.build_ms)} />
          <MetricRow label="Test" value={fmtMs(eng.test_ms)} />
          <MetricRow label="Iterations" value={eng.iteration_count} />
          <MetricRow label="Rollbacks" value={eng.rollback_count} />
        </Section>
        <Section title="Safety Delta">
          <MetricRow label="unsafe blocks" before={num(ev.unsafe_block_count_before)} after={num(ev.unsafe_block_count_after)} />
          <MetricRow label="raw pointers" before={num(ev.raw_ptr_count_before)} after={num(ev.raw_ptr_count_after)} />
          <MetricRow label="unsafe API" before={num(ev.unsafe_api_count_before)} after={num(ev.unsafe_api_count_after)} />
          <MetricRow label="manual mem" before={num(ev.manual_mem_call_count_before)} after={num(ev.manual_mem_call_count_after)} />
        </Section>
      </CardContent>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</p>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function MetricRow({ label, value, before, after }: {
  label: string;
  value?: string | number | undefined;
  before?: number;
  after?: number;
}) {
  if (before !== undefined && after !== undefined) {
    const delta = after - before;
    const color = delta < 0 ? "text-green-600" : delta > 0 ? "text-red-600" : "text-muted-foreground";
    return (
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span>
          {before} &rarr; {after}{" "}
          <span className={`font-mono text-xs ${color}`}>({delta > 0 ? "+" : ""}{delta})</span>
        </span>
      </div>
    );
  }
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono">{value ?? "-"}</span>
    </div>
  );
}

function fmtMs(v: number | undefined): string {
  if (v === undefined || v === null) return "-";
  return v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v}ms`;
}

function num(v: unknown): number {
  return typeof v === "number" ? v : 0;
}
