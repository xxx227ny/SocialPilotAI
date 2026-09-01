import { useEffect, useMemo, useRef, useState } from "react";

import { getApiErrorMessage } from "../../api/client";
import {
  compositionEnhancementPreviewUrl,
  compositionSubtitleContentUrl,
  getCompositionEnhancementArtifact,
  getCompositionEnhancementJob,
  listCompositionAudioArtifacts,
  preflightCompositionEnhancement,
  submitCompositionEnhancement,
} from "../../api/videoCompositionEnhancements";
import { videoCompositionEnhancementEnabled } from "../../config/features";
import { usePresentationMode } from "../../context/PresentationModeContext";
import type { ExecutionJob } from "../../types/execution";
import type { Product } from "../../types/product";
import type { VideoCompositionArtifact } from "../../types/videoComposition";
import type {
  CompositionAudioArtifact,
  CompositionEnhancementArtifact,
  CompositionEnhancementPreflight,
  SubtitleCueInput,
} from "../../types/videoCompositionEnhancement";
import {
  abortEnhancementOperation,
  beginEnhancementOperation,
  exactEnhancementResult,
  finishEnhancementOperation,
  pollExactEnhancementJob,
  type EnhancementIdentity,
} from "./videoCompositionEnhancementState";

const DEFAULT_CUES: SubtitleCueInput[] = [
  { sequence: 1, start_ms: 0, end_ms: 5000, text: "" },
  { sequence: 2, start_ms: 5000, end_ms: 10000, text: "" },
  { sequence: 3, start_ms: 10000, end_ms: 15000, text: "" },
];

type Operation = { controller: AbortController; id: number };

export function VideoCompositionEnhancementPanel({
  product,
  artifact,
}: {
  product: Product;
  artifact: VideoCompositionArtifact;
}) {
  const { isPresentation } = usePresentationMode();
  const [audio, setAudio] = useState<CompositionAudioArtifact[]>([]);
  const [voiceoverId, setVoiceoverId] = useState<number | null>(null);
  const [musicId, setMusicId] = useState<number | null>(null);
  const [cues, setCues] = useState(DEFAULT_CUES);
  const [preflight, setPreflight] =
    useState<CompositionEnhancementPreflight | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [job, setJob] = useState<ExecutionJob | null>(null);
  const [result, setResult] =
    useState<CompositionEnhancementArtifact | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState({ preflight: false, submit: false, result: false });
  const preflightOperation = useRef<Operation | null>(null);
  const submitOperation = useRef<Operation | null>(null);
  const resultOperation = useRef<Operation | null>(null);
  const pollOperation = useRef<EnhancementIdentity | null>(null);
  const sequence = useRef(0);
  const selectionIdentity = useMemo(
    () =>
      `${product.id}:${artifact.composition_id}:${artifact.id}:` +
      `${voiceoverId ?? ""}:${musicId ?? ""}:${JSON.stringify(cues)}`,
    [artifact.composition_id, artifact.id, cues, musicId, product.id, voiceoverId],
  );

  function abortOperations() {
    abortEnhancementOperation(preflightOperation);
    abortEnhancementOperation(submitOperation);
    abortEnhancementOperation(resultOperation);
    pollOperation.current?.controller.abort();
    pollOperation.current = null;
    setBusy({ preflight: false, submit: false, result: false });
  }

  useEffect(() => {
    abortOperations();
    setAudio([]);
    setVoiceoverId(null);
    setMusicId(null);
    setCues(DEFAULT_CUES);
    setPreflight(null);
    setConfirmed(false);
    setJob(null);
    setResult(null);
    setMessage("");
    if (!videoCompositionEnhancementEnabled || isPresentation) return;
    const controller = new AbortController();
    listCompositionAudioArtifacts(product.id, artifact.composition_id, controller.signal)
      .then((items) => {
        if (!controller.signal.aborted) setAudio(items);
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setMessage(getApiErrorMessage(error, "音频 Artifact 读取失败。"));
        }
      });
    return () => {
      controller.abort();
      abortOperations();
    };
  }, [artifact.composition_id, artifact.id, isPresentation, product.id]);

  useEffect(() => {
    abortOperations();
    setPreflight(null);
    setConfirmed(false);
    setJob(null);
    setResult(null);
    setMessage("");
  }, [selectionIdentity]);

  useEffect(() => {
    const artifactId = job ? exactEnhancementResult(job) : null;
    if (!artifactId || result?.id === artifactId) return;
    const operation = { controller: new AbortController(), id: ++sequence.current };
    if (!beginEnhancementOperation(resultOperation, operation)) return;
    setBusy((current) => ({ ...current, result: true }));
    getCompositionEnhancementArtifact(artifactId, operation.controller.signal)
      .then((next) => {
        if (
          resultOperation.current === operation &&
          !operation.controller.signal.aborted
        ) {
          setResult(next);
        }
      })
      .catch((error) => {
        if (
          resultOperation.current === operation &&
          !operation.controller.signal.aborted
        ) {
          setMessage(getApiErrorMessage(error, "增强成片读取失败，请显式重读。"));
        }
      })
      .finally(() => {
        if (finishEnhancementOperation(resultOperation, operation)) {
          setBusy((current) => ({ ...current, result: false }));
        }
      });
    return () => operation.controller.abort();
  }, [job, result]);

  if (!videoCompositionEnhancementEnabled || isPresentation) return null;
  const voiceovers = audio.filter((item) => item.kind === "voiceover");
  const music = audio.filter((item) => item.kind === "music");
  const validCues = cues.every(
    (cue) =>
      cue.text.trim() &&
      cue.start_ms >= 0 &&
      cue.end_ms <= 15000 &&
      cue.end_ms > cue.start_ms,
  );

  async function runPreflight() {
    if (!voiceoverId || !validCues) return;
    const operation = { controller: new AbortController(), id: ++sequence.current };
    if (!beginEnhancementOperation(preflightOperation, operation)) return;
    setBusy((current) => ({ ...current, preflight: true }));
    try {
      const next = await preflightCompositionEnhancement(
        product.id,
        {
          composition_id: artifact.composition_id,
          source_artifact_id: artifact.id,
          voiceover_artifact_id: voiceoverId,
          music_artifact_id: musicId,
          cues,
          style: {
            font_size: 48,
            max_chars_per_line: 18,
            bottom_margin: 280,
            outline_width: 3,
          },
          mix: {
            voiceover_gain_db: 0,
            music_gain_db: -18,
            ducking_reduction_db: 12,
            target_lufs: -14,
            true_peak_db: -1,
          },
        },
        operation.controller.signal,
      );
      if (
        preflightOperation.current === operation &&
        !operation.controller.signal.aborted
      ) {
        setPreflight(next);
        setMessage("");
      }
    } catch (error) {
      if (
        preflightOperation.current === operation &&
        !operation.controller.signal.aborted
      ) {
        setMessage(getApiErrorMessage(error, "增强 Preflight 失败。"));
      }
    } finally {
      if (finishEnhancementOperation(preflightOperation, operation)) {
        setBusy((current) => ({ ...current, preflight: false }));
      }
    }
  }

  async function submit() {
    if (!preflight) return;
    const operation = { controller: new AbortController(), id: ++sequence.current };
    if (!beginEnhancementOperation(submitOperation, operation)) return;
    setBusy((current) => ({ ...current, submit: true }));
    try {
      const response = await submitCompositionEnhancement(
        product.id,
        preflight,
        operation.controller.signal,
      );
      if (submitOperation.current !== operation || operation.controller.signal.aborted) {
        return;
      }
      setJob(response.job);
      setMessage(
        response.reused
          ? "已复用精确增强任务。"
          : "已创建本地音频字幕增强任务。",
      );
      const pollIdentity: EnhancementIdentity = {
        productId: product.id,
        compositionId: artifact.composition_id,
        artifactId: artifact.id,
        jobId: response.job.id,
        operationId: ++sequence.current,
        controller: new AbortController(),
      };
      pollOperation.current = pollIdentity;
      void pollExactEnhancementJob({
        identity: pollIdentity,
        current: () => pollOperation.current,
        read: getCompositionEnhancementJob,
        update: (nextJob) => {
          if (pollOperation.current === pollIdentity) setJob(nextJob);
        },
        temporaryFailure: () => {
          if (pollOperation.current === pollIdentity) {
            setMessage("本地任务读取暂时失败，将继续读取同一精确 Job。");
          }
        },
      }).finally(() => {
        if (pollOperation.current === pollIdentity) pollOperation.current = null;
      });
    } catch (error) {
      if (
        submitOperation.current === operation &&
        !operation.controller.signal.aborted
      ) {
        setMessage(getApiErrorMessage(error, "增强任务创建失败。"));
      }
    } finally {
      if (finishEnhancementOperation(submitOperation, operation)) {
        setBusy((current) => ({ ...current, submit: false }));
      }
    }
  }

  return (
    <section className="video-composition-enhancement-panel">
      <h5>Stage 3B · 真实配音、音乐、Ducking 与字幕</h5>
      <p>
        Stage 3A Artifact #{artifact.id} 的确定性静音 AAC 占位音轨将被真实配音替换；
        背景音乐可选，本地 FFmpeg 费用为零。
      </p>
      <label>
        配音 Artifact
        <select
          value={voiceoverId ?? ""}
          onChange={(event) =>
            setVoiceoverId(event.target.value ? Number(event.target.value) : null)
          }
        >
          <option value="">明确选择真实配音</option>
          {voiceovers.map((item) => (
            <option key={item.id} value={item.id}>
              Voiceover #{item.id} · {item.duration_ms}ms
            </option>
          ))}
        </select>
      </label>
      <label>
        背景音乐 Artifact（可选）
        <select
          value={musicId ?? ""}
          onChange={(event) =>
            setMusicId(event.target.value ? Number(event.target.value) : null)
          }
        >
          <option value="">不使用背景音乐</option>
          {music.map((item) => (
            <option key={item.id} value={item.id}>
              Music #{item.id} · {item.duration_ms}ms
            </option>
          ))}
        </select>
      </label>
      {cues.map((cue, index) => (
        <fieldset key={cue.sequence}>
          <legend>字幕 Cue #{cue.sequence}</legend>
          <input
            aria-label={`Cue ${cue.sequence} start`}
            type="number"
            value={cue.start_ms}
            onChange={(event) =>
              setCues((current) =>
                current.map((item, itemIndex) =>
                  itemIndex === index
                    ? { ...item, start_ms: Number(event.target.value) }
                    : item,
                ),
              )
            }
          />
          <input
            aria-label={`Cue ${cue.sequence} end`}
            type="number"
            value={cue.end_ms}
            onChange={(event) =>
              setCues((current) =>
                current.map((item, itemIndex) =>
                  itemIndex === index
                    ? { ...item, end_ms: Number(event.target.value) }
                    : item,
                ),
              )
            }
          />
          <textarea
            value={cue.text}
            onChange={(event) =>
              setCues((current) =>
                current.map((item, itemIndex) =>
                  itemIndex === index ? { ...item, text: event.target.value } : item,
                ),
              )
            }
          />
        </fieldset>
      ))}
      <button
        type="button"
        disabled={!voiceoverId || !validCues || busy.preflight || busy.submit}
        onClick={() => void runPreflight()}
      >
        Provider-free 增强 Preflight
      </button>
      {preflight && (
        <>
          <p>{preflight.execution_notice}</p>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            确认本地 CPU、音频混合与磁盘写入
          </label>
          <button
            type="button"
            disabled={!confirmed || busy.submit}
            onClick={() => void submit()}
          >
            创建真实音频字幕增强成片
          </button>
        </>
      )}
      {job && (
        <p>
          Enhancement Job #{job.id} · {job.status}
        </p>
      )}
      {result && (
        <>
          <p>
            Enhanced Artifact #{result.id} · {result.audio_codec.toUpperCase()} ·{" "}
            {result.subtitle_cue_count} cues ·{" "}
            {(result.measured_lufs_milli / 1000).toFixed(1)} LUFS
          </p>
          <video controls playsInline preload="metadata" src={compositionEnhancementPreviewUrl(result.id)} />
          <a href={compositionSubtitleContentUrl(result.subtitle_artifact_id)}>
            读取精确 WebVTT
          </a>
        </>
      )}
      {job?.status === "SUCCEEDED" && !result && (
        <button
          type="button"
          disabled={busy.result}
          onClick={() => setJob({ ...job })}
        >
          重新读取精确增强结果
        </button>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
