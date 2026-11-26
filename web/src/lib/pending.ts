/** Settings saves in flight; a run waits for them so unsaved choices are never ignored. */
const pending = new Set<Promise<unknown>>();

export function trackSave<T>(p: Promise<T>): Promise<T> {
  pending.add(p);
  p.finally(() => pending.delete(p)).catch(() => undefined);
  return p;
}

type Flusher = () => Promise<unknown> | undefined;
let flusher: Flusher | null = null;

/** The settings form registers a function that saves its unsaved changes immediately. */
export function registerFlusher(f: Flusher | null) {
  flusher = f;
}

export async function flushSaves() {
  const f = flusher?.();
  await Promise.allSettled([...pending, ...(f ? [f] : [])]);
}
