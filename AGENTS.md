# DeerFlow Repository Agent Guide

## Start Here

This checkout is not a plain upstream DeerFlow clone. It contains a local MMKB
integration that lets MMKB call DeerFlow as a separate agent runtime through
MMKB's OpenAI-compatible `model=agent` path.

Before making changes:

1. Read the closest scoped `AGENTS.md` and `CLAUDE.md` files for the area being
   changed.
2. For MMKB integration work, read:
   - `docs/MMKB_INTEGRATION_CHANGES.md` for the current implementation inventory.
   - `docs/MMKB_URL_LIFECYCLE.md` for RAG resource-link behavior.
   - `docs/MMKB_AGENT_STORAGE_AND_OOM_TROUBLESHOOTING.md` for storage
     configuration, long-running SSE, and memory-risk behavior.
3. Inspect the current worktree before editing. This repository may contain
   active local changes; do not revert or overwrite unrelated work.

`docs/MMKB_INTEGRATION_CHANGES.md` is the source of truth for MMKB-specific
DeerFlow modifications. Keep it synchronized with implementation changes.

## Repository Boundaries

The backend has a strict dependency direction:

- `backend/packages/harness/deerflow/` is the reusable agent framework. It must
  not import `app.*`.
- `backend/app/` is the Gateway and application layer. It may import
  `deerflow.*`.
- `frontend/` is the Next.js DeerFlow UI.
- `monitor/` is an optional operational dashboard, not part of the Gateway
  request path.

The harness/app boundary is enforced by
`backend/tests/test_harness_boundary.py`.

Prefer existing ownership boundaries over adding cross-layer helpers. In
particular, generic Agent/RAG behavior belongs in the harness, while Gateway
HTTP routing and authorization belong in `backend/app/`.

## MMKB Integration Invariants

MMKB remains responsible for authenticating users and enforcing workspace
document access. DeerFlow treats `mmkb_bearer_token` as opaque and only replays
it when calling MMKB APIs.

Preserve these invariants:

- The MMKB proxy authorization bypass is limited to run creation.
- Runtime memory and thread state remain isolated by MMKB `workspace + user`.
- Delegated subagents receive only the explicitly allowed MMKB authentication
  and identity context.
- RAG tools access MMKB through the semantic client/service layers; they do not
  read MMKB's database or server filesystem.
- `tools.py` owns LangChain schemas and serialization, not HTTP endpoint
  construction.
- `client.py` owns the current HTTP transport and implements the
  transport-neutral `MMKBClient` protocol.
- `service.py`, `assets.py`, and `mmkb_links.py` own shared response policy and
  must remain reusable by a future MCP transport.
- HTTP failures continue to return the established JSON error contract instead
  of unexpectedly escaping as tool exceptions.

Relevant implementation area:

```text
backend/packages/harness/deerflow/tools/custom/rag/
|-- context.py
|-- client.py
|-- service.py
|-- assets.py
|-- mmkb_links.py
`-- tools.py
```

## User-Visible Link Rules

Do not treat all links in an Agent response as equivalent:

- `document_url` points to `/documents/<uuid>`. It is an MMKB browser page and
  intentionally requires a logged-in browser session with the matching current
  workspace.
- `image_url`, `video_url`, and `video_thumbnail_url` must be signed by MMKB and
  returned as `/api/document-media/<token>` before anonymous chat frontends can
  render them.
- DeerFlow-generated `/mnt/user-data/outputs/...` paths are internal paths.
  MMKB converts them to signed `/api/agent/artifacts/<token>` download links.
- MMKB server paths such as `markdown_merged_path` are metadata only and must
  never be passed to sandbox file tools or shown as user-facing links.

MMKB owns media signing and cryptographic/expiry validation. DeerFlow stage 4
only absolutizes remaining relative URL-like fields and records diagnostics; it
must not invent signatures or silently repair malformed signed URLs.

Agents, SOUL files, and local research skills must instruct the model to copy
user-facing URLs exactly from `rag_*` results. Never construct a link from a
document or asset ID.

When changing link behavior, validate the complete path:

1. MMKB tool response shape.
2. DeerFlow stage-4 processing.
3. Signed URL structure.
4. Final assistant Markdown.
5. A real browser-equivalent fetch when the environment is available.

## Resource Observability

Resource-link diagnostics must be useful without leaking credentials or signed
tokens.

- Keep `mmkb_link_stage4`, `mmkb_tool_resource_validation`, and
  `assistant_resource_validation` as count-only aggregate logs.
- Include `thread_id` and `run_id` where available so tool responses can be
  compared with final assistant output.
- Do not log full URLs, bearer tokens, signed tokens, document IDs, or private
  server paths.
- DeerFlow validation is structure-only. It may detect truncation, malformed
  tokens, unexpected origins, or unsigned protected media, but MMKB remains
  responsible for signature validity, expiry, authorization, and file
  existence.
- A tool-layer-valid URL that becomes invalid in the assistant layer indicates
  model output mutation or truncation.

The optional monitor service reads aggregate runtime diagnostics. Start it
explicitly with the Docker Compose `monitor` profile:

```bash
docker compose -p deer-flow-dev -f docker/docker-compose-dev.yaml \
  --profile monitor up -d monitor
```

It binds to `127.0.0.1:9090`; remote access normally requires SSH port
forwarding. The monitor is optional and does not start unless its profile is
enabled.

## Documentation Policy

For every code change, follow the repository-wide documentation policy in
the root `CLAUDE.md`:

- Update `README.md` for user-facing behavior or setup changes.
- Update the relevant `CLAUDE.md` for architecture, commands, or development
  workflow changes.
- Keep `AGENTS.md` and `AGENTS_ZH.md` synchronized when repository rules change.

Additionally, update `docs/MMKB_INTEGRATION_CHANGES.md` whenever a change
affects MMKB integration, including:

- Gateway authentication or authorization for MMKB proxy requests.
- `mmkb_bearer_token`, `public_base_url`, MMKB identity, or runtime user
  handling.
- MMKB RAG tools, link processing, resource validation, or observability.
- `research-analyst` configuration/SOUL or local research skills.
- MMKB-related tool registration, Docker startup, or monitor behavior.

Update `docs/MMKB_URL_LIFECYCLE.md` when user-visible RAG resource-link stages
or validation boundaries change.

## Verification

Every feature or bug fix must include relevant automated tests unless it cannot
be tested automatically; document the reason when no automated test is added.

During development, run the smallest relevant checks first. Before declaring a
change complete, run the full relevant suite when changing shared contracts,
runtime boundaries, authentication, persistence, or broadly used behavior.
For narrow isolated changes, run all directly affected checks and state any
remaining full-suite risk.

Backend formatting and lint:

```bash
cd backend
uv run ruff check <changed paths>
uv run ruff format --check <changed paths>
```

Focused MMKB integration tests:

```bash
cd backend
PYTHONPATH=. uv run pytest \
  tests/test_mmkb_client.py \
  tests/test_mmkb_links.py \
  tests/test_mmkb_resource_validation.py \
  tests/test_mmkb_asset_tools.py \
  tests/test_mmkb_tools_contract.py \
  tests/test_run_journal.py -v
```

Also run tests that match the changed boundary:

- Gateway auth/context changes: relevant Gateway tests plus MMKB proxy tests.
- Harness architecture changes: `tests/test_harness_boundary.py`.
- Memory isolation changes: memory storage, middleware, and custom-agent tests.
- Docker/monitor changes: render the Compose configuration and verify the
  affected service is healthy.
- Frontend changes: follow `frontend/AGENTS.md` and run the relevant unit/E2E
  checks.

Do not claim that a user-visible resource link works based only on JSON shape or
unit tests when a real fetch can be performed.

## Sensitive And Runtime Files

Do not commit real secrets.

- `.env` must remain local-only.
- Prefer `.env.example` for variable names and setup hints.
- `DEER_FLOW_INTERNAL_AUTH_TOKEN` must match MMKB at runtime, but its real value
  must not appear in documentation, logs, or committed files.
- Real bearer tokens, signed resource tokens, and secrets must not appear in
  tests, logs, documentation, or committed files. Tests may use clearly
  synthetic placeholder values.

Treat `backend/.deer-flow/**/memory.json`, thread directories, generated
artifacts, logs, and monitor output as runtime state. Commit runtime memory only
when explicitly seeding or migrating it.

## Upstream Sync

When syncing with `bytedance/deer-flow`, prefer a fresh upstream comparison and
3-way merge/patch workflow. Do not overwrite this checkout with an upstream
tree.

Re-check the MMKB integration areas documented in
`docs/MMKB_INTEGRATION_CHANGES.md`, especially:

- `backend/app/gateway/authz.py`
- `backend/app/gateway/services.py`
- `backend/packages/harness/deerflow/config/agents_config.py`
- `backend/packages/harness/deerflow/tools/custom/rag/`
- `backend/packages/harness/deerflow/runtime/`
- `config.yaml`
- `scripts/docker.sh`
- `docker/docker-compose-dev.yaml`
- `monitor/`

After resolving upstream changes, verify that MMKB can still create
`model=agent` runs, delegated RAG tools retain workspace-scoped bearer context,
resource links remain usable, artifact downloads resolve the correct runtime
user bucket, and memory remains isolated by `workspace + user`.
