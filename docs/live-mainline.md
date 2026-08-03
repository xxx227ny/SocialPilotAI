# V2-L1 local live mainline

All real-AI gates remain disabled by default. Live validation must use a
repository-external SQLite database and Artifact directory. Never place keys,
Workspace IDs, Provider task IDs, signed URLs, databases, videos, or logs in
Git.

## Backend process configuration

Configure these variables locally without committing their values:

- `QWEN_API_KEY`: the Qwen credential. `DASHSCOPE_API_KEY` is accepted only as
  a deprecated one-way alias when `QWEN_API_KEY` is absent. Neither name is a
  Wanx credential.
- `QWEN_WORKSPACE_ID`, `QWEN_REGION=cn-beijing`, and optionally the exact
  controlled `QWEN_ENDPOINT` ending in `/compatible-mode/v1`.
- `WANX_API_KEY`: the independent Wanx credential. It is never used by Qwen.
- `WANX_WORKSPACE_ID`, `WANX_REGION=cn-beijing`, and optionally the exact
  controlled `WANX_ENDPOINT` ending in `/api/v1`.
- `QWEN_MODEL=qwen-plus` and `WANX_MODEL=wan2.7-t2v`.
- `QWEN_CONNECT_TIMEOUT=10`, `QWEN_READ_TIMEOUT=120`,
  `QWEN_WRITE_TIMEOUT=30`, and `QWEN_POOL_TIMEOUT=10`. The Backend has no
  shorter application response deadline, while Qwen execution requests in
  the Frontend wait 180 seconds.
- `DATABASE_URL`: an absolute repository-external Live SQLite URL.
- `VIDEO_ARTIFACT_STORAGE_ROOT`: an absolute repository-external directory.
- `REQUIRE_LIVE_PROVIDER_COHERENCE=true`.
- `ENABLE_GROWTH_EXECUTION=true`.
- `ENABLE_COPY_EXECUTION=true`.
- `ENABLE_V2_COPY_EXECUTION=true`.
- `ENABLE_V2_VIDEO_PROJECT_EXECUTION=true`.
- `ENABLE_VIDEO_RENDER_EXECUTION=true`.

Qwen and Wanx keys, Workspaces, and endpoints may differ. Strict Live
coherence validates each Provider only against its own credential, Workspace,
region, endpoint, and model; it never compares the two keys or derives one
Provider from the other. Missing or inconsistent fields fail closed before
Provider resolution. Public Preflight results expose only readiness booleans
and safe requirement categories, never configuration values.

Qwen SDK retries remain disabled. Safe Provider failure metadata is limited to
Provider, phase, HTTP status, allowlisted error category, a short stable
SHA-256 request-ID digest, uncertainty, possible billing, and timestamp. It
never retains the Provider message, prompt, key, Authorization header, full
Workspace, full endpoint, signed URL, or raw request ID. HTTP 400/401/403/404,
429, connection-before-send, and strict output validation are definitive.
HTTP 408, read timeout, indeterminate write timeout, post-send disconnect, and
an indeterminate sent 5xx are uncertain and must never be retried
automatically. Browser response loss remains a Frontend uncertainty and does
not rewrite Backend facts.

## Frontend process configuration

Set the matching frontend gates only for the local Live build:

- `VITE_ENABLE_GROWTH_EXECUTION=true`
- `VITE_ENABLE_COPY_EXECUTION=true`
- `VITE_ENABLE_V2_COPY_EXECUTION=true`
- `VITE_ENABLE_V2_VIDEO_PROJECT_EXECUTION=true`
- `VITE_ENABLE_VIDEO_RENDER_EXECUTION=true`

Presentation Mode never inherits these permissions. Page load, Product
switching, and Preflight are read-only. Every generation action requires its
own single-use fee confirmation, which is consumed synchronously when the
request starts. Generation is never automatically retried.

## Safe execution order

1. Read the exact Product and FeedbackContext.
2. Run Recommendation Preflight, confirm once, and execute once.
3. Run V2 Copy Preflight, confirm once, and execute once.
4. Run V2 VideoProject Preflight, confirm once, and execute once.
5. The exact generated VideoProject is handed to Render Preflight.
6. Confirm Wanx cost once and submit one RenderTask once.
7. Refresh only the same task until a safe terminal state.
8. Play and download only through stable Backend Artifact URLs.

`SUBMIT_UNKNOWN` is a stop condition. It must not be bypassed with another
submit or a replacement task.

## Recommendation transport error contract

Recommendation execution uses `QWEN_API_KEY` through the same independent
readiness function in Preflight, the route gate, and the Service second gate.
The deprecated `DASHSCOPE_API_KEY` alias is never a separate execution
requirement when `QWEN_API_KEY` is present.

Backend-owned failures return only a safe message. Classified Provider
failures return only `provider`, `phase`, `provider_http_status`,
`safe_error_code`, the optional 16-hex `request_id_digest`, `uncertain`,
`potentially_billable`, and `occurred_at`. A null Provider status proves that
no Provider HTTP response was observed. Local proxy/connect failures are
non-billable; response timeout, post-send delivery loss, and Provider 5xx are
treated conservatively. Raw Provider messages, response bodies, request IDs,
prompts, endpoints, Workspaces, and credentials are never included.

The Qwen OpenAI-compatible base URL ends exactly once in
`/compatible-mode/v1`; the SDK appends exactly one `/chat/completions` path.
The HTTP client explicitly honors the process proxy environment, uses the
configured connect/read/write/pool timeouts, and has automatic retries set to
zero.

## Verified V2-L1 delivery outcome

The 2026-08-03 V2-L1N run used explicitly approved normal-system networking
for the Live Backend. Restricted Sandbox execution remains unsuitable and
forbidden for real Provider calls. Preflight connectivity verified Qwen and
Wanx readiness plus TCP, TLS, and unauthenticated HTTP reachability without a
generation request or credential disclosure.

One continuous user-controlled browser session completed the following paid
sequence with separate single-use confirmations:

1. Recommendation Qwen: 1 successful call.
2. V2 Copy Qwen: 1 successful call. Platform evidence was Source and Allowed
   `TikTok / Instagram / Facebook`, with Recommendation Target and V2 Copy
   Target both `TikTok`. Backend persisted CopyMatrix #3 with `TikTok`.
3. V2 VideoProject Qwen: 1 successful call. Backend persisted planned
   VideoProject #2, bound to CopyMatrix #3, with `TikTok`, 10 seconds, `9:16`,
   two continuous scenes, and an exact 10-second scene sum.
4. Wanx: 1 successful Submit created RenderTask #1. One explicit same-task
   refresh reached `SUCCEEDED`; automatic polling and replacement Submit were
   0.

Artifact #1 is `video/mp4`, 1,501,205 bytes, with SHA-256
`8EA00B62025B93E4604F22C585940AD04B7B73C27155017112624624B6D55361`.
The stable Backend Content endpoint returned 200, HEAD returned 200 with no
body, `bytes=0-99` returned 206 with 100 bytes, and Download returned the full
file with the same size and digest. Browser playback loaded while paused, and
a page reload recovered VideoProject #2, RenderTask #1, Artifact #1, playback,
and download through exact persisted identities.

There were no automatic retries, duplicate Qwen POSTs, or duplicate Wanx
Submits. The run may have billed three Qwen generations and one Wanx
generation. Provider task identity, transient Provider URL, credentials,
Workspace, endpoints, prompts, and raw Provider responses remain excluded
from Frontend state, documentation, and Git. V2-L1 is complete; V2-L2 remains
outside this checkpoint.
