import { Badge } from "@/components/ui/badge";

const STATUS_COLORS: Record<string, string> = {
  OK: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  STOP: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  FAILED: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  RUNNING: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  INIT: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200",
  pass: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  fail: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  skip: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  error: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = status || "unknown";
  const color = STATUS_COLORS[s] || "bg-gray-100 text-gray-700";
  return <Badge className={`${color} font-mono text-xs`}>{s}</Badge>;
}

export function RiskBadge({ level }: { level: string }) {
  const colors: Record<string, string> = {
    high: "bg-red-100 text-red-800",
    medium: "bg-yellow-100 text-yellow-800",
    low: "bg-green-100 text-green-800",
  };
  return <Badge className={`${colors[level] || "bg-gray-100 text-gray-700"} text-xs`}>{level}</Badge>;
}

export function ModeBadge({ mode }: { mode: string | null | undefined }) {
  const m = mode || "unknown";
  const color = m === "enhanced"
    ? "bg-purple-100 text-purple-800"
    : "bg-gray-100 text-gray-700";
  return <Badge className={`${color} text-xs`}>{m}</Badge>;
}
