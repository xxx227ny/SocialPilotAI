import { useEffect, useState } from "react";

import { getDemoSnapshot } from "../api/dashboard";
import type { DashboardSnapshot } from "../types/dashboard";

export function useDemoSnapshot() {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void getDemoSnapshot()
      .then((result) => {
        if (!active) return;
        setSnapshot(result);
        setError("");
      })
      .catch(() => {
        if (!active) return;
        setError("Demo Snapshot 尚未准备，请在比赛前完成预置数据准备。");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return { snapshot, loading, error };
}
