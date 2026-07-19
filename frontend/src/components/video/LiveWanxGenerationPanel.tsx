import { useEffect, useRef, useState } from "react";

import {
  createLiveVideoRender,
  refreshVideoRenderTask,
} from "../../api/videos";
import type {
  VideoRenderTaskStatus,
} from "../../types/video";
import { executeLiveGeneration } from "./liveWanxGeneration";

interface LiveWanxGenerationPanelProps {
  videoProjectId: number;
  onArtifactReady: () => Promise<void>;
}

export function LiveWanxGenerationPanel({
  videoProjectId,
  onArtifactReady,
}: LiveWanxGenerationPanelProps) {
  const [confirming, setConfirming] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [working, setWorking] = useState(false);
  const [status, setStatus] = useState<VideoRenderTaskStatus | null>(null);
  const [message, setMessage] = useState("");
  const runIdRef = useRef(0);

  useEffect(
    () => () => {
      runIdRef.current += 1;
    },
    [],
  );

  async function confirmGeneration() {
    if (working) return;
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;
    setWorking(true);
    setAttempted(true);
    setConfirming(false);
    setMessage("");

    try {
      const result = await executeLiveGeneration({
        videoProjectId,
        create: createLiveVideoRender,
        refresh: refreshVideoRenderTask,
        onStatus: setStatus,
        onArtifactReady,
        isActive: () => runIdRef.current === runId,
      });
      if (runIdRef.current !== runId) return;
      setStatus(result.task.status);

      if (result.task.status === "SUCCEEDED" && result.artifact) {
        if (runIdRef.current === runId) {
          setMessage("Live creative completed and verified.");
        }
      } else {
        setMessage(
          result.task.status === "FAILED"
            ? "Live generation failed. The verified video above is unchanged."
            : "Live generation stopped before completion. The verified video above is unchanged.",
        );
      }
    } catch {
      if (runIdRef.current === runId) {
        setMessage(
          "Live generation is unavailable. The verified video above is unchanged.",
        );
      }
    } finally {
      if (runIdRef.current === runId) setWorking(false);
    }
  }

  return (
    <section className="live-wanx-panel">
      <header>
        <div>
          <span>Live Wanx Demo · Optional</span>
          <h2>Generate a new creative, once</h2>
        </div>
        {status && (
          <strong className={`live-wanx-panel__status live-wanx-panel__status--${status.toLowerCase()}`}>
            {status}
          </strong>
        )}
      </header>

      {!confirming && !attempted && status === null && (
        <div className="live-wanx-panel__intro">
          <p>
            Optional live proof using the fixed Demo Scene 1. The pre-generated
            video remains available if the live request cannot complete.
          </p>
          <button type="button" onClick={() => setConfirming(true)}>
            Generate New Creative
          </button>
        </div>
      )}

      {confirming && status === null && (
        <div className="live-wanx-panel__confirmation">
          <div className="live-wanx-panel__facts">
            <LiveFact label="Duration" value="3 seconds" />
            <LiveFact label="Resolution" value="720P" />
            <LiveFact label="Aspect ratio" value="9:16" />
            <LiveFact label="Estimated cost" value="≈ $0.258" />
            <LiveFact label="Estimated wait" value="1–5 minutes" />
            <LiveFact label="Limit" value="One generation only" />
          </div>
          <p>
            This submits one real Wanx generation. There is no automatic retry
            and no second task will be created for repeated confirmation.
          </p>
          <div className="live-wanx-panel__actions">
            <button
              className="live-wanx-panel__cancel"
              type="button"
              onClick={() => setConfirming(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={working}
              onClick={() => void confirmGeneration()}
            >
              Confirm One Live Generation
            </button>
          </div>
        </div>
      )}

      {status && (
        <div className="live-wanx-panel__progress">
          <div aria-hidden="true" className={working ? "is-active" : ""} />
          <p>
            {working
              ? "One live task is in progress. Status refresh runs every 15 seconds."
              : message}
          </p>
          <small>1 live Wanx generation submitted · no automatic retry</small>
        </div>
      )}

      {!status && message && (
        <p className="live-wanx-panel__message">{message}</p>
      )}
    </section>
  );
}

function LiveFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}
