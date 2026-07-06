# CLAUDE.md

This file provides repository-level guidance for working with this DeerFlow
checkout.

## Project Context

DeerFlow is a LangGraph-based agent system with four main repository areas:

- `backend/`: Gateway API and embedded agent runtime.
- `frontend/`: Next.js DeerFlow user interface.
- `docker/`: Local Docker development and optional provisioner configuration.
- `monitor/`: Optional container-memory and MMKB resource-diagnostics dashboard.

This checkout also contains a local MMKB integration. MMKB authenticates its own
users, calls DeerFlow through the OpenAI-compatible `model=agent` path, and
provides workspace-scoped RAG APIs used by DeerFlow tools.

For MMKB-specific implementation details, use
`docs/MMKB_INTEGRATION_CHANGES.md` as the source of truth. For user-visible RAG
resource links, read `docs/MMKB_URL_LIFECYCLE.md`.

For a complete map of the `docs/` directory, start with `docs/README.md`. It
lists the purpose of each current document and gives reading order by task.
High-frequency references:

- `docs/deploy.md`: shortest MMKB-integrated Docker deployment flow.
- `docs/MMKB_INTEGRATION_CHANGES.md`: source of truth for current MMKB-specific
  DeerFlow changes.
- `docs/MMKB_URL_LIFECYCLE.md`: RAG document/media/artifact URL lifecycle.
- `docs/MMKB_AGENT_STORAGE_AND_OOM_TROUBLESHOOTING.md`: storage, long-running
  SSE, and OOM investigation notes.
- `docs/CONFIG_YAML_REFERENCE.md`: supported `config.yaml` fields and runtime
  boundaries.
- `docs/MEMORY_IMPLEMENTATION.md`: long-term memory data flow, storage, and
  injection behavior.

## Scoped Guidance

Read the closest scoped guidance before changing a directory:

- Repository-wide rules: `AGENTS.md`
- Chinese reference translation: `AGENTS_ZH.md`
- Backend architecture and commands: `backend/CLAUDE.md`
- Backend agent pointer: `backend/AGENTS.md`
- Frontend architecture and commands: `frontend/CLAUDE.md`
- Frontend agent guidance: `frontend/AGENTS.md`

The root `AGENTS.md` defines cross-repository invariants. More specific
subdirectory guidance may add stricter requirements for that area, but should
not contradict the root rules.

## Architecture Boundaries

The backend has a strict dependency direction:

- `backend/packages/harness/deerflow/` is the reusable agent framework and must
  not import `app.*`.
- `backend/app/` is the Gateway/application layer and may import `deerflow.*`.

MMKB RAG integrations belong under
`backend/packages/harness/deerflow/tools/custom/rag/` and use a semantic
client/service split. Transport details belong in the client implementation;
shared response, asset, and link policies must remain transport-neutral.

The optional `monitor/` service observes aggregate runtime diagnostics. It must
not become a dependency of the Gateway request path.

## Development Commands

Run full-application commands from the repository root:

```bash
make check
make install
make dev
make stop
```

For backend-only commands and tests, read `backend/CLAUDE.md`. For frontend-only
commands and tests, read `frontend/CLAUDE.md`.

Docker development startup:

```bash
make docker-init
make docker-start
```

`make docker-start` uses `scripts/docker.sh start`. That script sources the
project-root `.env`, exports the local restricted-network mirrors
`APT_MIRROR=mirrors.tuna.tsinghua.edu.cn`,
`UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`, and
`NPM_REGISTRY=https://registry.npmmirror.com`, then runs
`scripts/check_deerflow_internal_auth.sh` with `DEER_FLOW_BASE_URL=""` before
building containers. The pre-start check validates that MMKB and DeerFlow
`.env` files contain matching `DEER_FLOW_INTERNAL_AUTH_TOKEN` values without
requiring DeerFlow to already be running. It may be skipped only for emergency
local debugging with `DEER_FLOW_SKIP_PRE_START_CHECKS=1`.

Start the optional monitor service explicitly:

```bash
docker compose -p deer-flow-dev -f docker/docker-compose-dev.yaml \
  --profile monitor up -d monitor
```

The monitor binds to `127.0.0.1:9090` and normally requires SSH port forwarding
for remote access.

## Documentation Policy

Keep documentation proportional to the change:

- Update `README.md` when user-visible behavior, setup, or usage changes.
- Update the relevant `CLAUDE.md` when architecture, commands, development
  workflows, or internal ownership boundaries change.
- Update `docs/MMKB_INTEGRATION_CHANGES.md` whenever MMKB integration behavior
  changes.
- Update `docs/MMKB_URL_LIFECYCLE.md` whenever the RAG resource-link lifecycle
  or validation boundaries change.
- Keep `AGENTS.md` and `AGENTS_ZH.md` synchronized.

Documentation-only edits do not require unrelated README or CLAUDE updates.

## Verification Policy

Every feature or bug fix must include relevant automated tests unless the change
cannot be tested automatically; document the reason when no automated test is
added.

During development, run the smallest relevant checks first. Before declaring the
change complete:

- Run all directly affected tests and linters.
- Run the full relevant suite when changing shared contracts, runtime
  boundaries, authentication, persistence, or broadly used behavior.
- For narrow isolated changes, state which focused checks were run and any
  remaining full-suite risk.

Documentation-only changes require formatting, link/path, and consistency
checks, but not unrelated code test suites.

## Sensitive And Runtime Data

Never commit or log real secrets, bearer tokens, or signed resource tokens.
Tests may use clearly synthetic placeholder values.

Treat `.env`, runtime memory, thread state, generated artifacts, logs, and
monitor output as local runtime data unless a task explicitly requires seeding
or migrating them.
