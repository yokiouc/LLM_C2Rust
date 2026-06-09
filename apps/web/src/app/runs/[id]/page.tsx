"use client";

import { use } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useRunStatus, useRunHotspots, useRunSlices, useRunValidation, useRunMetrics, useRunPatches } from "@/hooks/use-runs";
import { useRunSteps } from "@/hooks/use-steps";
import { RunStatusCard } from "@/components/run/run-status-card";
import { MetricsCard } from "@/components/run/metrics-card";
import { HotspotTable } from "@/components/run/hotspot-table";
import { SliceTable } from "@/components/run/slice-table";
import { ValidationTimeline } from "@/components/run/validation-timeline";
import { PatchDiff } from "@/components/run/patch-diff";
import { FSMTimeline } from "@/components/run/fsm-timeline";
import { LoadingState, ErrorState } from "@/components/shared/empty-state";

export default function RunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: runId } = use(params);

  const status = useRunStatus(runId);
  const hotspots = useRunHotspots(runId);
  const slices = useRunSlices(runId);
  const validation = useRunValidation(runId);
  const metrics = useRunMetrics(runId);
  const patches = useRunPatches(runId);
  const steps = useRunSteps(runId);

  if (status.isLoading) return <LoadingState />;
  if (status.error) return <ErrorState message={status.error instanceof Error ? status.error.message : "Failed to load run"} />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Run Detail</h1>
        <p className="font-mono text-sm text-muted-foreground">{runId}</p>
      </div>

      {/* Status card */}
      {status.data && <RunStatusCard data={status.data} />}

      {/* Validation pipeline */}
      <div>
        <h2 className="mb-2 text-sm font-semibold">Validation Pipeline</h2>
        {validation.isLoading && <LoadingState />}
        {validation.data && <ValidationTimeline data={validation.data} />}
        {validation.error && <p className="text-sm text-muted-foreground">Validation data unavailable</p>}
      </div>

      {/* Main tabs */}
      <Tabs defaultValue="timeline">
        <TabsList>
          <TabsTrigger value="timeline">
            FSM Timeline {steps.data ? `(${steps.data.count})` : ""}
          </TabsTrigger>
          <TabsTrigger value="hotspots">
            Hotspots {hotspots.data ? `(${hotspots.data.count})` : ""}
          </TabsTrigger>
          <TabsTrigger value="slices">
            Slices {slices.data ? `(${slices.data.count})` : ""}
          </TabsTrigger>
          <TabsTrigger value="patches">
            Patches {patches.data ? `(${patches.data.patches.length})` : ""}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="timeline" className="mt-3">
          {steps.isLoading && <LoadingState />}
          {steps.data && <FSMTimeline steps={steps.data.steps} />}
          {steps.error && <p className="text-sm text-muted-foreground">Step data unavailable</p>}
        </TabsContent>

        <TabsContent value="hotspots" className="mt-3">
          {hotspots.isLoading && <LoadingState />}
          {hotspots.data && <HotspotTable hotspots={hotspots.data.hotspots} />}
          {hotspots.error && <p className="text-sm text-muted-foreground">Hotspot data unavailable</p>}
        </TabsContent>

        <TabsContent value="slices" className="mt-3">
          {slices.isLoading && <LoadingState />}
          {slices.data && <SliceTable slices={slices.data.slices} />}
          {slices.error && <p className="text-sm text-muted-foreground">Slice data unavailable</p>}
        </TabsContent>

        <TabsContent value="patches" className="mt-3">
          {patches.isLoading && <LoadingState />}
          {patches.data && <PatchDiff data={patches.data} />}
          {patches.error && <p className="text-sm text-muted-foreground">Patch data unavailable</p>}
        </TabsContent>
      </Tabs>

      {/* Metrics */}
      {metrics.data && <MetricsCard data={metrics.data} />}
    </div>
  );
}
