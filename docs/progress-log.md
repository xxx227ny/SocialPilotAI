# SocialPilot AI Progress Log

This log records evidence-backed checkpoints. It does not convert plans into completed work or assign a result to a historical commit unless preserved or executed.

## Historical checkpoints

| Date | Checkpoint | Commit | Evidence and result | Known limitations |
|---:|---|---|---|---|
| 2026-07-17 | C0-C2 stable baseline | `61dd14e` | Initial modular backend, React frontend, product-to-growth chain, tests, README, and architecture. No earlier independent C0/C1/C2 commits or totals exist here. | Early stages share one baseline commit. |
| 2026-07-17 | Qwen verification | `57df1d1` | `docs/qwen_verification.md` records one successful `qwen-plus` smoke: 1 passed; output parsed and validated. | Historical paid/provider call; normal tests skip it. |
| 2026-07-17 | Artifact infrastructure | `9e3a740` | Model, repository, schema, service behavior, and tests added. | Provider URL is not long-term storage. |
| 2026-07-17 | Wanx adapter | `25f17d8` | Submit/fetch adapter, safe error mapping, configuration, and mock tests added. | External network, credentials, region, and provider behavior remain dependencies. |
| 2026-07-17 | Render execution pipeline | `027eccb` | Submit claim, refresh/status sync, Artifact creation, API and service tests added. | Polling must never silently resubmit. |
| 2026-07-19 | Wanx real verification | `5f0a5f9` | Opt-in real smoke and safety controls added; tracked docs state successful task-to-Artifact verification. | Real smoke is cost-bearing and disabled by default. |
| 2026-07-19 | Verified output/live facade | `9e23124` | Read-only Artifact display, default-off facade, frontend panel, and tests added. | Temporary provider URL may expire. |
| 2026-07-21 | Competition freeze | `9877216`; tag `competition-freeze-v1` | Docs, local verified MP4, submission docs, and presentation guidance added. Preserved gate: 84 passed, 2 skipped, 1 warning; Ruff and frontend build passed. | Performance-to-Prompt, second-version generation, and version tracking remain absent. |

## V2-C0 — Safe branch, project map, and development tree

- Status: ✅ Completed.
- Date: 2026-07-21.
- Starting point: `competition-freeze-v1` → `98772160208840eff2f00b97b78ae34809b1786f`.
- Branch: `competition-product-v2`, created directly from the freeze tag.
- Freeze verification: `master`, the tag, and the branch starting HEAD resolve to the same commit.
- Pre-check: clean tree, no pre-existing V2 branch, no untracked files.
- Product-code changes: none.
- Real AI calls: none.
- V2-C0 checkpoint: see this Git commit.
- Push: not performed as part of this checkpoint.
- Next stage: V2-C1.1A Product creation form and validation.

### Quality gate

| Gate | Scope | Result |
|---|---|---|
| Backend | Unit/mock suite with `qwen_smoke` and `wanx_smoke` excluded | 86 collected; 2 deselected; 84 passed; 0 failed; 1 known Starlette deprecation warning |
| Ruff | Backend check | All checks passed |
| TypeScript | `tsc -b` via frontend build | Passed |
| Production build | Vite | Passed; 118 modules transformed |

The first frontend build attempt ran from the backend directory and failed with `ENOENT` because no `package.json` exists there. It was rerun from the correct frontend directory and passed. This operational mistake did not modify product source.

### Document set

- `docs/development-roadmap.md`
- `docs/progress-log.md`
- `docs/v2-plan.md`

## V2 stage update template

```markdown
## YYYY-MM-DD — V2-Cx.y Stage name

- Status:
- Starting branch and HEAD:
- Scope authorized:
- Preconditions verified:
- Files changed (explicit allowlist):
- Database/schema impact:
- Provider/AI calls: none, or approved model/count/cost envelope
- Implementation summary:
- Tests executed and exact results:
- Warnings, skips, and failures:
- Security/privacy checks:
- git diff --stat:
- git diff --check:
- Commit: none until explicitly authorized
- Push: none until explicitly authorized
- Known issues:
- Rollback point:
- Single recommended next stage:
```

## Update rules

1. Record only commands actually run and results observed.
2. Never hide failed attempts, warnings, skips, or unavailable capabilities.
3. Do not start a second V2 stage in the same update.
4. Do not mark a stage complete before its gate passes.
5. Stage explicit files only; never use `git add .`.
6. Commit and push only after explicit approval.
7. Real Qwen/Wanx smoke requires a separate cost/risk report and approval.
