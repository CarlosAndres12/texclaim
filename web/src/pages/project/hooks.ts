import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

export function useReport(pid: string, enabled = true) {
  return useQuery({
    queryKey: ["report", pid],
    queryFn: () => api.report(pid),
    enabled,
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 1,
  });
}

export function useOutline(pid: string) {
  return useQuery({ queryKey: ["outline", pid], queryFn: () => api.outline(pid), retry: false, staleTime: 30_000 });
}

export const isNotFound = (e: unknown) => e instanceof ApiError && e.status === 404;
