# Controlled Real Wanx Render Verification Evidence

## Verification identity

- Stage: V2-C3.1C
- Date: 2026-07-27
- Contract Commit: `7257c189f0ebdec6a53b800e988a3012d129afd6`
- Provider: Alibaba Cloud Bailian / Wanx
- Model: `wan2.7-t2v`
- Region: `cn-beijing`
- Type: Text-to-Video

## Authorization and call budget

| Operation | Authorized maximum | Actual |
|---|---:|---:|
| Wanx Submit | 1 | 1 |
| Wanx Refresh | 19 | 3 |
| Provider output download | 1 | 1 |
| Automatic retry | 0 | 0 |
| Outer retry | 0 | 0 |
| Qwen call | 0 | 0 |
| Live Demo call | 0 | 0 |

The minimum authorized Refresh interval was 15 seconds. The authorization was
fully consumed when this controlled verification ended.

## Execution result

- `render-execution` POST: 1
- Execution HTTP result: 200
- Refresh HTTP results: 3 requests, all HTTP 200
- State transition: `PENDING → RUNNING → RUNNING → SUCCEEDED`
- Final RenderTask status: `SUCCEEDED`
- Total elapsed time: 49.3 seconds
- Second Submit: none
- `SUBMIT_UNKNOWN`: not reached
- Artifact storage failure: none

## Redacted input summary

- Scene: Scene 1
- Requested duration: 2 seconds
- Requested aspect ratio: `9:16`
- Requested resolution: `720P`
- Prompt summary: a short, non-sensitive portable-blender product scene

The complete Prompt is intentionally not recorded.

## Exact execution associations

- Product records: 1
- MarketingStrategy records: 1
- CopyMatrix records: 1
- VideoProject records: 1
- VideoRenderTask records: 1
- VideoRenderArtifact records: 1
- The RenderTask was associated with the exact VideoProject.
- The RenderTask execution unit was Scene 1.
- Product, MarketingStrategy, and CopyMatrix associations were verified.
- VideoProject has no persisted MarketingBrief foreign key.

Product, Strategy, CopyMatrix, and VideoProject were deterministic local
preparation data in isolated temporary SQLite. Qwen was not used to create any
of them. The verification covered the Wanx render execution, state recovery,
and Artifact persistence contract.

## Artifact evidence

- Content-Type: `video/mp4`
- File size: 825,844 bytes
- SHA-256:
  `e30bbdb2904b28b73b227f652593c4da4517e293d1680fc9aec3c97a5bfc33ce`
- `storage_path`: controlled relative path
- Provider temporary URL persisted as a long-term playback address: no
- Database size metadata matched the stable content: yes
- Database SHA-256 metadata matched the stable content: yes
- Stable content API read: passed
- Second output download: 0

## Media properties and visual-acceptance boundary

- The final MP4 was not parsed with `ffprobe`, a media player, or a video
  decoder.
- `720P`, `9:16`, and 2 seconds are request parameters.
- Those request parameters are not represented as independently parsed final
  file media properties.
- Codec, actual resolution, actual duration, frame rate, and audio-track state
  were not independently confirmed.
- No human playback or visual-quality acceptance was completed.
- The success conclusion covers only: Provider task success, successful file
  download, successful Artifact persistence, matching hash metadata, and
  successful stable content API reading.
- The temporary Artifact was deleted after successful verification. The
  generated video is not retained as a permanent evidence asset.

## Current product boundary

- Only Scene 1 is generated.
- This is not a multi-scene composite video.
- Refresh is an explicit operation, not automatic background polling.
- `SUBMIT_UNKNOWN` still requires manual reconciliation.
- Artifact persistence currently uses a local filesystem.
- Object storage is not implemented.
- No dedicated HTTP Range-support claim is made.
- VideoProject has no MarketingBrief foreign key.

## Security protection

- API Key value was not output.
- Workspace ID value was not output.
- Authorization Header was not output.
- Provider Task ID value was not output.
- The complete Prompt was not recorded.
- Provider raw request and response were not recorded.
- Provider signed URL was not recorded.
- Private local paths were not recorded.
- Repository `.env`, database, and frozen MP4 were not modified.

## Temporary-environment cleanup

- Temporary SQLite was deleted.
- The Artifact directory and generated video were deleted.
- The execution script, logs, progress data, and result file were deleted.
- Ports 8000 and 5173 had no listeners after cleanup.
- The Git working tree remained clean after the real verification.

## Cost and authorization boundary

- The real Submit may have consumed Alibaba Cloud Bailian Credits.
- Exact Credits, monetary cost, and remaining balance were neither queried nor
  invented.
- The single-Submit authorization is exhausted.
- Refresh and output-download authorization also ended.
- A new independent user authorization is required before any further Submit,
  Refresh, or Provider-output access.

See the [Development Roadmap](development-roadmap.md) and
[Progress Log](progress-log.md) for the stage record.
