import { useCallback, useEffect, useMemo, useSyncExternalStore, type SetStateAction } from "react";
import { getReadResource } from "./readResourceStore";
export { initialReadState, failedReadState } from "./readResourceStore";
export type { ReadState } from "./readResourceStore";

export function useReadResource<T>(key: string, loader: (signal: AbortSignal) => Promise<T>) {
  const resource = useMemo(() => getReadResource<T>(key), [key]);
  const state = useSyncExternalStore(resource.subscribe, resource.snapshot, resource.snapshot);
  const refresh = useCallback(() => { void resource.load(loader, true); }, [resource, loader]);
  useEffect(() => {
    void resource.load(loader);
    const recover = () => { void resource.load(loader); };
    window.addEventListener("online", refresh);
    window.addEventListener("focus", recover);
    return () => {
      // Route changes retain the shared read. Auth changes and writes cancel it.
      window.removeEventListener("online", refresh);
      window.removeEventListener("focus", recover);
    };
  }, [resource, loader, refresh]);
  const updateData = useCallback((action: SetStateAction<T | null>) => resource.update(action), [resource]);
  return { ...state, refresh, updateData };
}
