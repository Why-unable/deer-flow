# DeerFlow Agent Guide

## Project Context

This DeerFlow checkout is not a plain upstream clone. It contains a local MMKB
integration branch that lets MMKB call DeerFlow as a separate agent runtime via
the OpenAI-compatible `model=agent` path.

When working in this repository, treat `docs/MMKB_INTEGRATION_CHANGES.md` as the
source of truth for MMKB-specific DeerFlow changes.

## Required MMKB Documentation Update

When changing any MMKB integration behavior in this repository, update:

- `docs/MMKB_INTEGRATION_CHANGES.md`

This includes changes to:

- Gateway authentication or authorization for MMKB proxy requests
- `mmkb_bearer_token`, `public_base_url`, `mmkb_workspace_id`, `mmkb_user_id`, or `mmkb_tenant_id` handling
- MMKB runtime user or memory isolation behavior
- MMKB RAG tools under `backend/packages/harness/deerflow/tools/custom/rag/`
- `research-analyst` agent config or SOUL
- `local-deep-research` skill behavior
- `local-systematic-literature-review` skill behavior
- `config.yaml` tool registration related to MMKB
- Docker startup or restart behavior used by the MMKB integration

If a change does not affect MMKB integration, no update is required.

## Sensitive And Runtime Files

Do not commit real secrets.

- `.env` must remain local-only.
- Prefer `.env.example` for variable names and setup hints.
- `DEER_FLOW_INTERNAL_AUTH_TOKEN` must match MMKB's value at runtime, but the
  real value should not be written into documentation or committed files.

Be careful with runtime memory files.

- `backend/.deer-flow/**/memory.json` is runtime state, not integration logic.
- Commit memory only when explicitly intending to seed or migrate memory.
- For normal development, prefer shared agent definitions plus per-user runtime
  memory created by DeerFlow.

## Rebase / Upstream Sync

When syncing with upstream `bytedance/deer-flow`, re-check the MMKB integration
areas documented in `docs/MMKB_INTEGRATION_CHANGES.md`, especially:

- `backend/app/gateway/authz.py`
- `backend/app/gateway/services.py`
- `backend/packages/harness/deerflow/config/agents_config.py`
- `backend/packages/harness/deerflow/tools/custom/rag/tools.py`
- `config.yaml`
- `scripts/docker.sh`
- `docker/docker-compose-dev.yaml`

After resolving upstream changes, verify that MMKB can still start
`model=agent` runs, RAG tools can call MMKB with the forwarded bearer token, and
memory is isolated by `workspace + user`.
