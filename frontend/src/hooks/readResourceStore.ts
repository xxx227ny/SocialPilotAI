import axios from "axios";

export interface ReadState<T> {
  key: string;
  data: T | null;
  loading: boolean;
  error: unknown | null;
  loadedAt: number | null;
}

export function initialReadState<T>(key: string): ReadState<T> {
  return { key, data: null, loading: true, error: null, loadedAt: null };
}

export function failedReadState<T>(state: ReadState<T>, error: unknown): ReadState<T> {
  const unavailable = axios.isAxiosError(error) && [401, 403, 404, 410].includes(error.response?.status ?? 0);
  return { ...state, loading: false, error, ...(unavailable ? { data: null, loadedAt: null } : {}) };
}

export class ReadResource<T> {
  state: ReadState<T>;
  listeners = new Set<() => void>();
  private controller: AbortController | null = null;
  private pending: Promise<void> | null = null;
  private freshUntil = 0;
  private retryAfter = 0;
  private revision = 0;
  private loader: ((signal: AbortSignal) => Promise<T>) | null = null;
  constructor(readonly key: string) { this.state = initialReadState(key); }
  snapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  private publish(state: ReadState<T>) {
    this.state = state;
    this.listeners.forEach(listener => listener());
  }
  load(loader: (signal: AbortSignal) => Promise<T>, force = false): Promise<void> {
    this.loader = loader;
    if (this.pending) return this.pending;
    if (!force && Date.now() < Math.max(this.freshUntil, this.retryAfter)) return Promise.resolve();
    const active = new AbortController();
    this.controller = active;
    this.publish({ ...this.state, loading: true, error: null });
    this.pending = Promise.resolve().then(() => {
      if (active.signal.aborted) return;
      return loader(active.signal);
    }).then(data => {
      if (active.signal.aborted) return;
      this.freshUntil = Date.now() + 30_000;
      this.retryAfter = 0;
      this.publish({ key: this.key, data: data as T, loading: false, error: null, loadedAt: Date.now() });
    }).catch((error: unknown) => {
      if (active.signal.aborted) return;
      this.freshUntil = 0;
      this.retryAfter = Date.now() + 5000;
      this.publish(failedReadState(this.state, error));
    }).finally(() => {
      if (this.controller === active) { this.pending = null; this.controller = null; }
    });
    return this.pending;
  }
  invalidate(clear = false, revalidate = false) {
    const revision = ++this.revision;
    this.controller?.abort();
    this.controller = null;
    this.pending = null;
    this.freshUntil = this.retryAfter = 0;
    this.publish(clear ? initialReadState(this.key) : { ...this.state, loading: false });
    if (revalidate) queueMicrotask(() => {
      if (revision === this.revision && this.listeners.size && this.loader) void this.load(this.loader, true);
    });
  }
  update(action: T | null | ((current: T | null) => T | null)) {
    this.invalidate();
    const data = typeof action === "function" ? (action as (current: T | null) => T | null)(this.state.data) : action;
    this.freshUntil = Date.now() + 30_000;
    this.publish({ key: this.key, data, loading: false, error: null, loadedAt: Date.now() });
  }
  get busy() { return this.pending !== null; }
}

// Memory only: API responses never persist across login sessions or to disk.
const resources = new Map<string, ReadResource<unknown>>();
export function getReadResource<T>(key: string): ReadResource<T> {
  let resource = resources.get(key);
  if (!resource) {
    for (const [oldKey, old] of resources) {
      if (resources.size < 100) break;
      if (!old.listeners.size && !old.busy) resources.delete(oldKey);
    }
    resource = new ReadResource(key);
    resources.set(key, resource);
  }
  return resource as ReadResource<T>;
}

export function clearReadResources() {
  resources.forEach((entry, key) => {
    entry.invalidate(true);
    if (!entry.listeners.size) resources.delete(key);
  });
}

export function invalidateReadResources(deletedProductId?: string) {
  resources.forEach(entry => entry.invalidate(
    deletedProductId !== undefined && ["products", `product:${deletedProductId}`, `briefs:${deletedProductId}`].includes(entry.key),
    true,
  ));
}
