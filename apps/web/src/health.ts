export type Health = {
  status: "ready" | "degraded" | "loading";
  components?: Record<string, { status: string; error?: string }>;
};

export function componentStatus(health: Health, name: string): string {
  return health.components?.[name]?.status ?? "unknown";
}
