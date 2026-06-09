"use client";

import { useQuery } from "@tanstack/react-query";
import {
  listRuns,
  getRunStatus,
  getRunHotspots,
  getRunSlices,
  getRunValidation,
  getRunMetrics,
  getRunPatches,
  getCompare,
} from "@/lib/api";

export function useRuns() {
  return useQuery({
    queryKey: ["runs"],
    queryFn: () => listRuns(),
    retry: 1,
  });
}

export function useRunStatus(runId: string) {
  return useQuery({
    queryKey: ["run-status", runId],
    queryFn: () => getRunStatus(runId),
    enabled: !!runId,
    retry: 1,
  });
}

export function useRunHotspots(runId: string) {
  return useQuery({
    queryKey: ["run-hotspots", runId],
    queryFn: () => getRunHotspots(runId),
    enabled: !!runId,
    retry: 1,
  });
}

export function useRunSlices(runId: string) {
  return useQuery({
    queryKey: ["run-slices", runId],
    queryFn: () => getRunSlices(runId),
    enabled: !!runId,
    retry: 1,
  });
}

export function useRunValidation(runId: string) {
  return useQuery({
    queryKey: ["run-validation", runId],
    queryFn: () => getRunValidation(runId),
    enabled: !!runId,
    retry: 1,
  });
}

export function useRunMetrics(runId: string) {
  return useQuery({
    queryKey: ["run-metrics", runId],
    queryFn: () => getRunMetrics(runId),
    enabled: !!runId,
    retry: 1,
  });
}

export function useRunPatches(runId: string) {
  return useQuery({
    queryKey: ["run-patches", runId],
    queryFn: () => getRunPatches(runId),
    enabled: !!runId,
    retry: 1,
  });
}

export function useCompare(baselineId: string, enhancedId: string) {
  return useQuery({
    queryKey: ["compare", baselineId, enhancedId],
    queryFn: () => getCompare(baselineId, enhancedId),
    enabled: !!baselineId && !!enhancedId,
    retry: 1,
  });
}
