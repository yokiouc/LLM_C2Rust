"use client";

import { useState } from "react";
import Link from "next/link";
import { useCompare, useRuns } from "@/hooks/use-runs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/shared/status-badge";
import { LoadingState, ErrorState, EmptyState } from "@/components/shared/empty-state";
import type { CompareResponse } from "@/lib/api/types";

type FormalCase = {
  id: string;
  title: string;
  data: CompareResponse & {
    baseline: CompareResponse["baseline"] & { lint_ok: boolean; patch_count: number; stop_reason: string };
    enhanced: CompareResponse["enhanced"] & { lint_ok: boolean; patch_count: number };
  };
};

const FORMAL_CASES: FormalCase[] = [
  {
    id: "CF-02",
    title: "CF-02 pointer arithmetic",
    data: {
      project: "CF-02 ptr_arithmetic_fixture",
      baseline: {
        run_id: "f3a1ddb3-b310-4ea7-9eaf-7523f8f794cb",
        compile_ok: true,
        test_ok: true,
        lint_ok: true,
        unsafe_blocks: 1,
        raw_ptr_count: 0,
        total_ms: 632,
        patch_count: 0,
        stop_reason: "success",
      },
      enhanced: {
        run_id: "61f143dc-1b4b-4607-b3ba-9faf385a359e",
        compile_ok: true,
        test_ok: true,
        lint_ok: true,
        unsafe_blocks: 0,
        raw_ptr_count: 0,
        total_ms: 6331,
        iterations: 1,
        rollbacks: 0,
        patch_count: 1,
        stop_reason: "success",
      },
      delta: { unsafe_blocks: -1, raw_ptr: 0, unsafe_api: 0 },
    },
  },
  {
    id: "CF-03",
    title: "CF-03 ptr copy",
    data: {
      project: "CF-03 ptr_copy_fixture",
      baseline: {
        run_id: "a61a7789-d0f6-4639-8a05-be51a98668ec",
        compile_ok: true,
        test_ok: true,
        lint_ok: true,
        unsafe_blocks: 1,
        raw_ptr_count: 0,
        total_ms: 624,
        patch_count: 0,
        stop_reason: "success",
      },
      enhanced: {
        run_id: "14e973ed-644a-4b4e-8f14-cdcd0ff95e33",
        compile_ok: true,
        test_ok: true,
        lint_ok: true,
        unsafe_blocks: 0,
        raw_ptr_count: 0,
        total_ms: 14223,
        iterations: 2,
        rollbacks: 1,
        patch_count: 2,
        stop_reason: "success",
      },
      delta: { unsafe_blocks: -1, raw_ptr: 0, unsafe_api: 0 },
    },
  },
  {
    id: "SW-04",
    title: "SW-04 C-derived buffer copy",
    data: {
      project: "SW-04 logc_c_derived_workspace",
      baseline: {
        run_id: "1d60bcf2-1c8b-411c-b38f-1fa4d29957d2",
        compile_ok: true,
        test_ok: true,
        lint_ok: true,
        unsafe_blocks: 1,
        raw_ptr_count: 0,
        total_ms: 739,
        patch_count: 0,
        stop_reason: "success",
      },
      enhanced: {
        run_id: "25c97630-3756-48d1-8220-f685aae60046",
        compile_ok: true,
        test_ok: true,
        lint_ok: true,
        unsafe_blocks: 0,
        raw_ptr_count: 0,
        total_ms: 7148,
        iterations: 1,
        rollbacks: 0,
        patch_count: 1,
        stop_reason: "success",
      },
      delta: { unsafe_blocks: -1, raw_ptr: 0, unsafe_api: 0 },
    },
  },
  {
    id: "SW-03",
    title: "SW-03 parser pointer walk",
    data: {
      project: "SW-03 inih_c_derived_workspace",
      baseline: {
        run_id: "c0956794-a838-4420-b3f6-e4be958a54c2",
        compile_ok: true,
        test_ok: true,
        lint_ok: true,
        unsafe_blocks: 1,
        raw_ptr_count: 0,
        total_ms: 645,
        patch_count: 0,
        stop_reason: "success",
      },
      enhanced: {
        run_id: "bcd76169-0f13-41a0-91ea-266cccba4a11",
        compile_ok: false,
        test_ok: false,
        lint_ok: false,
        unsafe_blocks: 1,
        raw_ptr_count: 0,
        total_ms: 11381,
        iterations: 2,
        rollbacks: 2,
        patch_count: 2,
        stop_reason: "max_iters / context_mismatch",
      },
      delta: { unsafe_blocks: 0, raw_ptr: 0, unsafe_api: 0 },
    },
  },
];

export default function ComparePage() {
  const { data: runs } = useRuns();
  const [baselineId, setBaselineId] = useState("");
  const [enhancedId, setEnhancedId] = useState("");
  const [confirmedBaselineId, setConfirmedBaselineId] = useState("");
  const [confirmedEnhancedId, setConfirmedEnhancedId] = useState("");
  const [formalCaseId, setFormalCaseId] = useState("CF-02");
  const [confirmedFormalCaseId, setConfirmedFormalCaseId] = useState("CF-02");

  // Auto-detect pairs from runs
  const baselineRuns = runs?.filter((r) => typeof r.mode === "string" && r.mode === "baseline") || [];
  const enhancedRuns = runs?.filter((r) => typeof r.mode === "string" && r.mode === "enhanced") || [];

  const draftBaseline = baselineId || baselineRuns[0]?.run_id || "";
  const draftEnhanced = enhancedId || enhancedRuns[0]?.run_id || "";
  const effectiveBaseline = confirmedBaselineId || baselineRuns[0]?.run_id || "";
  const effectiveEnhanced = confirmedEnhancedId || enhancedRuns[0]?.run_id || "";

  const compare = useCompare(effectiveBaseline, effectiveEnhanced);
  const useFormalFallback = runs !== undefined && baselineRuns.length === 0;
  const formalCase = FORMAL_CASES.find((item) => item.id === confirmedFormalCaseId) || FORMAL_CASES[0];

  function confirmSelection() {
    if (useFormalFallback) {
      setConfirmedFormalCaseId(formalCaseId);
      return;
    }
    setConfirmedBaselineId(draftBaseline);
    setConfirmedEnhancedId(draftEnhanced);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Baseline vs Enhanced</h1>
        <p className="text-sm text-muted-foreground">Compare repair runs side by side</p>
      </div>

      {/* Run selectors */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">Baseline Run</label>
          <select
            className="w-full rounded border bg-background px-3 py-2 text-sm"
            value={useFormalFallback ? formalCaseId : draftBaseline}
            onChange={(e) => {
              if (useFormalFallback) {
                setFormalCaseId(e.target.value);
                return;
              }
              setBaselineId(e.target.value);
            }}
          >
            {useFormalFallback ? (
              FORMAL_CASES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.data.baseline.run_id.slice(0, 8)} - {item.id} baseline
                </option>
              ))
            ) : (
              <>
                <option value="">Select baseline...</option>
                {baselineRuns.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id.slice(0, 8)} - {r.task_description?.slice(0, 30) || r.ref}
                  </option>
                ))}
              </>
            )}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">Enhanced Run</label>
          <select
            className="w-full rounded border bg-background px-3 py-2 text-sm"
            value={useFormalFallback ? formalCaseId : draftEnhanced}
            onChange={(e) => {
              if (useFormalFallback) {
                setFormalCaseId(e.target.value);
                return;
              }
              setEnhancedId(e.target.value);
            }}
          >
            {useFormalFallback ? (
              FORMAL_CASES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.data.enhanced.run_id.slice(0, 8)} - {item.title}
                </option>
              ))
            ) : (
              <>
                <option value="">Select enhanced...</option>
                {enhancedRuns.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id.slice(0, 8)} - {r.task_description?.slice(0, 30) || r.ref}
                  </option>
                ))}
              </>
            )}
          </select>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={confirmSelection} disabled={!useFormalFallback && (!draftBaseline || !draftEnhanced)}>
          Confirm Compare
        </Button>
        {!useFormalFallback && draftEnhanced && (
          <Link
            href={`/runs/${draftEnhanced}`}
            className="inline-flex h-8 items-center rounded-lg border px-2.5 text-sm font-medium hover:bg-muted"
          >
            Open Enhanced Run
          </Link>
        )}
      </div>

      {/* Comparison results */}
      {!useFormalFallback && compare.isLoading && <LoadingState />}
      {!useFormalFallback && compare.error && <ErrorState message="Comparison unavailable. Select valid baseline and enhanced runs." />}

      {!useFormalFallback && !effectiveBaseline && !effectiveEnhanced && (
        <EmptyState title="No runs selected" message="Run demo or pilot to generate baseline/enhanced pairs." />
      )}

      {useFormalFallback && <CompareCards data={formalCase.data} />}
      {!useFormalFallback && compare.data && <CompareCards data={compare.data} />}
    </div>
  );
}

function CompareCards({ data }: { data: CompareResponse | FormalCase["data"] }) {
  const baselineLint = "lint_ok" in data.baseline ? data.baseline.lint_ok : undefined;
  const enhancedLint = "lint_ok" in data.enhanced ? data.enhanced.lint_ok : undefined;
  const baselinePatchCount = "patch_count" in data.baseline ? data.baseline.patch_count : 0;
  const enhancedPatchCount = "patch_count" in data.enhanced ? data.enhanced.patch_count : undefined;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Correctness</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div />
            <div className="text-center font-medium">Baseline</div>
            <div className="text-center font-medium">Enhanced</div>

            <div className="text-muted-foreground">Build</div>
            <div className="text-center"><StatusBadge status={data.baseline.compile_ok ? "pass" : "fail"} /></div>
            <div className="text-center"><StatusBadge status={data.enhanced.compile_ok ? "pass" : "fail"} /></div>

            <div className="text-muted-foreground">Test</div>
            <div className="text-center"><StatusBadge status={data.baseline.test_ok ? "pass" : "fail"} /></div>
            <div className="text-center"><StatusBadge status={data.enhanced.test_ok ? "pass" : "fail"} /></div>

            <div className="text-muted-foreground">Lint</div>
            <div className="text-center"><StatusBadge status={baselineLint === false ? "fail" : "pass"} /></div>
            <div className="text-center"><StatusBadge status={enhancedLint === false ? "fail" : "pass"} /></div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Safety Metrics</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-4 gap-4 text-sm">
            <div />
            <div className="text-center font-medium">Baseline</div>
            <div className="text-center font-medium">Enhanced</div>
            <div className="text-center font-medium">Delta</div>

            <div className="text-muted-foreground">unsafe blocks</div>
            <div className="text-center font-mono">{data.baseline.unsafe_blocks}</div>
            <div className="text-center font-mono">{data.enhanced.unsafe_blocks}</div>
            <DeltaCell value={data.delta.unsafe_blocks} />

            <div className="text-muted-foreground">raw pointers</div>
            <div className="text-center font-mono">{data.baseline.raw_ptr_count}</div>
            <div className="text-center font-mono">{data.enhanced.raw_ptr_count}</div>
            <DeltaCell value={data.delta.raw_ptr} />

            <div className="text-muted-foreground">unsafe API</div>
            <div className="text-center font-mono">-</div>
            <div className="text-center font-mono">-</div>
            <DeltaCell value={data.delta.unsafe_api} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Cost</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div />
            <div className="text-center font-medium">Baseline</div>
            <div className="text-center font-medium">Enhanced</div>

            <div className="text-muted-foreground">Duration</div>
            <div className="text-center font-mono">{fmtMs(data.baseline.total_ms)}</div>
            <div className="text-center font-mono">{fmtMs(data.enhanced.total_ms)}</div>

            <div className="text-muted-foreground">Patches</div>
            <div className="text-center font-mono">{baselinePatchCount}</div>
            <div className="text-center font-mono">{enhancedPatchCount ?? "-"}</div>

            <div className="text-muted-foreground">Iterations</div>
            <div className="text-center font-mono">0</div>
            <div className="text-center font-mono">{data.enhanced.iterations}</div>

            <div className="text-muted-foreground">Rollbacks</div>
            <div className="text-center font-mono">0</div>
            <div className="text-center font-mono">{data.enhanced.rollbacks}</div>

            <div className="text-muted-foreground">Stop Reason</div>
            <div className="text-center text-xs">success</div>
            <div className="text-center text-xs">{data.enhanced.stop_reason || "-"}</div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function DeltaCell({ value }: { value: number }) {
  const color = value < 0 ? "text-green-600" : value > 0 ? "text-red-600" : "text-muted-foreground";
  const prefix = value > 0 ? "+" : "";
  return <div className={`text-center font-mono font-medium ${color}`}>{prefix}{value}</div>;
}

function fmtMs(v: number | undefined): string {
  if (!v) return "-";
  return v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v}ms`;
}
