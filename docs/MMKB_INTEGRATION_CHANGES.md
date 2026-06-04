# MMKB Integration Changes

This document records the local DeerFlow changes made for MMKB integration.
It is intended for future development, review, deployment, and rebasing against
upstream `bytedance/deer-flow`.

## Summary

The integration turns DeerFlow into a separate agent runtime for MMKB:

```text
OpenWebUI / OpenAI-compatible client
  -> MMKB /v1/chat/completions model=agent
  -> DeerFlow Gateway /api/threads/{thread_id}/runs/stream
  -> DeerFlow agent + custom RAG tools
  -> MMKB authenticated document/search APIs
```

MMKB remains responsible for user/workspace authentication. DeerFlow accepts
an internal MMKB proxy run, receives the original MMKB bearer token as an
opaque value, and replays that token only when calling MMKB tools.

The main integration goals are:

- expose DeerFlow through MMKB's OpenAI-compatible `model=agent` mode;
- let DeerFlow search/read MMKB's local knowledge base through authenticated
  HTTP tools;
- keep agent definitions shared while isolating memory per
  `workspace + user`;
- preserve local-document research behavior through a custom agent and skill;
- make local Docker restart/development easier after backend/tool/config
  changes.

## Authentication And Identity

### Internal Gateway Bypass

Files:

- `backend/app/gateway/authz.py`
- `backend/app/gateway/services.py`
- `backend/CLAUDE.md`

MMKB authenticates the external client first, then calls DeerFlow Gateway with:

- `config.configurable.mmkb_bearer_token`: original MMKB
  `Bearer <workspace_id>:<api_key>` token;
- `context.public_base_url`: public MMKB base URL for user-visible links;
- `context.mmkb_workspace_id`, `context.mmkb_user_id`,
  `context.mmkb_tenant_id`: authenticated MMKB identity metadata;
- `X-DeerFlow-Internal-Token`: shared internal secret;
- matching CSRF header/cookie pair.

`authz.py` adds `_is_mmkb_proxy_run_create(...)`, allowing only
`resource="runs"` and `action="create"` requests through when the body contains
a syntactically valid `mmkb_bearer_token`. DeerFlow does not parse or validate
the token. The MMKB tools validate it later against MMKB APIs.

`services.py` adds:

- `public_base_url`, `mmkb_workspace_id`, `mmkb_user_id`, and
  `mmkb_tenant_id` to the context/configurable allowlist;
- `resolve_mmkb_proxy_user(...)`, which maps MMKB identity into a path-safe
  DeerFlow runtime user id:

```text
mmkb-<workspace_id>-<user_id>
```

This user id is passed into DeerFlow's runtime user context for the duration of
run creation, then reset in a `finally` block.

Purpose:

- MMKB can start DeerFlow runs without requiring the DeerFlow UI session auth.
- DeerFlow memory/checkpoint behavior can isolate MMKB users by
  `workspace + user`.
- MMKB API authorization remains authoritative for document access.

Important boundary:

- The bypass is intentionally narrow: it only creates runs.
- Tool calls still fail with MMKB `401/403` if the forwarded bearer token is
  invalid, expired, or no longer authorized.

## Shared Agent Definitions, Isolated Memory

Files:

- `backend/packages/harness/deerflow/config/agents_config.py`
- `backend/tests/test_custom_agent.py`

Before this change, a user-specific agent directory existing under
`.deer-flow/users/<user>/agents/<agent>/` could prevent fallback to the shared
agent definition, even if that directory only contained `memory.json`.

`resolve_agent_dir(...)` now treats a user-specific agent as real only when:

```text
users/<user>/agents/<agent>/config.yaml
```

exists.

If the user directory contains only `memory.json`, DeerFlow falls back to the
shared/global agent config and SOUL.

Purpose:

- agent definition is shared globally;
- each MMKB `workspace + user` gets separate memory;
- deleting or creating per-user memory directories does not require copying
  full agent configs for every user.

Tests added in `backend/tests/test_custom_agent.py` verify both:

- config fallback when a user directory contains only `memory.json`;
- SOUL fallback under the same condition.

## Custom MMKB RAG Tools

Files:

- `backend/packages/harness/deerflow/tools/custom/__init__.py`
- `backend/packages/harness/deerflow/tools/custom/rag/__init__.py`
- `backend/packages/harness/deerflow/tools/custom/rag/tools.py`
- `config.yaml`

Seven custom tools were added under the `knowledge` tool group:

| Tool | MMKB endpoint | Purpose |
|---|---|---|
| `rag_list_documents` | `GET /api/documents?status=ready&limit=N` | discover ready documents |
| `rag_search` | `GET /api/search?q=&mode=&limit=` | search chunks and visual assets |
| `rag_get_document` | `GET /api/documents/<id>` | read one document's metadata |
| `rag_get_document_preview` | `GET /api/documents/<id>/preview` | read merged markdown preview |
| `rag_get_document_chunks` | `GET /api/documents/<id>/chunks` | inspect indexed chunks |
| `rag_get_document_assets` | `GET /api/documents/<id>/assets` | inspect extracted visual assets |
| `rag_list_collections` | `GET /api/collections` | inspect collection hierarchy |

Tool behavior:

- Base URL comes from each tool's `base_url` config, defaulting to
  `http://host.docker.internal:8000` for Docker-to-host MMKB access.
- Runtime `public_base_url` takes priority for absolutizing returned URLs.
- Runtime `mmkb_bearer_token` is added as the `Authorization` header.
- HTTP failures are returned as JSON error objects rather than raising.
- Relative `*_url`, `*_path`, and `*_base` fields are converted to absolute
  URLs when possible.
- Tool docstrings explicitly warn that MMKB paths such as
  `markdown_merged_path` are API metadata, not sandbox-readable files. Agents
  should not pass them to `read_file`, `grep`, or `bash`.

Purpose:

- DeerFlow can use MMKB as a local knowledge source without direct database or
  filesystem access.
- The same MMKB bearer authorization applies to agent-side retrieval.
- Visual assets can be included using public `image_url` values.

Config registration in `config.yaml`:

```yaml
tools:
  - name: rag_search
    group: knowledge
    use: deerflow.tools.custom.rag.tools:rag_search_tool
    base_url: http://host.docker.internal:8000
    timeout: 30
```

The same pattern is used for all seven RAG tools.

## Research Analyst Agent

Files:

- `.deer-flow/agents/research-analyst/config.yaml`
- `.deer-flow/agents/research-analyst/SOUL.md`
- `backend/.deer-flow/agents/research-analyst/config.yaml`
- `backend/.deer-flow/agents/research-analyst/SOUL.md`
- `backend/.deer-flow/users/default/agents/research-analyst/config.yaml`
- `backend/.deer-flow/users/default/agents/research-analyst/SOUL.md`

The `research-analyst` custom agent is configured as a local-knowledge-grounded
research assistant.

Current config:

```yaml
name: research-analyst
description: A precision-first, citation-aware, local-knowledge-grounded research agent for AI systems architects
model: qwen-plus
tool_groups:
  - knowledge
  - web
  - file:read
  - file:write
  - bash
skills:
  - local-deep-research
```

SOUL behavior:

- prefer local knowledge when the question can be answered from MMKB;
- use `rag_search` before web tools for local-document questions;
- inspect document metadata, previews, chunks, and assets before strong claims;
- treat OCR/caption evidence cautiously;
- distinguish local evidence, external web context, and inference;
- use subagents only when the research task can be split into independent
  dimensions;
- output in Chinese unless the user asks otherwise.

Why multiple copies exist:

- Root `.deer-flow/agents/...` represents project-root local agent state.
- `backend/.deer-flow/agents/...` is the backend/container runtime location.
- `backend/.deer-flow/users/default/...` preserves the default-user runtime
  copy for local testing.

Maintenance note:

- Prefer keeping the shared definition under the global `agents/` path.
- Avoid copying full agent definitions into every MMKB user directory. Per-user
  directories should generally hold memory only.

## Local Deep Research Skill

File:

- `skills/custom/local-deep-research/SKILL.md`

This skill defines the research workflow for local knowledge-base questions.

Main guidance:

- load the skill before research-heavy local-document answers;
- start with broad `rag_search`;
- use query variants, aliases, Chinese/English terms, and document titles;
- inspect previews/chunks/assets for important evidence;
- handle visual assets using `hit`, `from_chunk_ids`, `image_url`,
  `caption_or_ocr`, and asset ids;
- only use web search as limited external background when local evidence is
  insufficient;
- produce source-aware final answers with evidence boundaries.

Purpose:

- prevent the agent from treating local RAG as a single-shot lookup;
- make local-document research systematic and reproducible;
- improve visual evidence handling for figures, tables, screenshots, and OCR.

## Root Config And Extension Config

Files:

- `config.yaml`
- `extensions_config.json`

`config.yaml` is a full local runtime config. Integration-relevant parts are:

- model provider uses `CHAT_COMPLETION_API_KEY`;
- custom MMKB RAG tools are registered under the `knowledge` group;
- skills path defaults to project `skills/`;
- sandbox/file/bash tools remain available according to the agent config.

`extensions_config.json` adds a local MCP/extension config skeleton with
filesystem, GitHub, and Postgres MCP servers disabled by default.

Important git note:

- The repository `.gitignore` ignores `config.yaml` and `extensions_config.json`.
- They are currently staged as local integration files.
- Decide deliberately whether they should be committed to a private fork. If
  committed, they become part of the deployable MMKB-integrated DeerFlow state.

## Docker And Local Startup

Files:

- `Makefile`
- `scripts/docker.sh`
- `docker/docker-compose-dev.yaml`
- `README.md`

Changes:

- Added `make docker-restart-gateway`.
- Added `scripts/docker.sh restart-gateway`.
- `scripts/docker.sh` now sources project-root `.env` before running Docker
  Compose, so compose substitutions and `env_file` see the same values.
- Added default mirrors for local/restricted-network development:
  - `APT_MIRROR=mirrors.ustc.edu.cn`
  - `UV_INDEX_URL=https://mirrors.ustc.edu.cn/pypi/web/simple`
  - `NPM_REGISTRY=https://registry.npmmirror.com`
  - `UV_IMAGE=ghcr.io/astral-sh/uv:0.7.20`
- Removed explicit `DEER_FLOW_INTERNAL_AUTH_TOKEN=${...:-}` from gateway
  compose environment so it does not override the `.env` / `env_file` value
  with an empty string.
- README gained a short MMKB integration note.

Common commands:

```bash
make docker-start
make docker-restart-gateway
make docker-logs-gateway
```

Use `docker-restart-gateway` after changes to:

- Gateway auth/services code;
- custom RAG tools;
- `config.yaml`;
- internal token / environment wiring.

## Environment Variables

File:

- `.env`

Current local `.env` contains variables with these names:

```text
TAVILY_API_KEY
JINA_API_KEY
INFOQUEST_API_KEY
DASHSCOPE_API_KEY
CHAT_COMPLETION_API_KEY
MULTIMODAL_EMBED_API_KEY
PADDLEX_API_TOKEN
DEER_FLOW_INTERNAL_AUTH_TOKEN
```

Purpose:

- model/tool provider keys;
- shared internal MMKB-to-DeerFlow Gateway token.

Security note:

- Do not commit real `.env` values to a public repository.
- In a private fork, committing `.env` is still risky and should be avoided
  unless the repository is explicitly treated as a private deployment bundle.
- Prefer committing `.env.example` with variable names only and creating the
  real `.env` on each target machine.
- `DEER_FLOW_INTERNAL_AUTH_TOKEN` must match the value configured in MMKB.

Current repository warning:

- `.env` is ignored by `.gitignore`, but is currently staged.
- Before pushing to GitHub, run:

```bash
git status --short
git restore --staged .env
```

If `.env` has become tracked in git history, remove it from tracking:

```bash
git rm --cached .env
```

Then keep a local-only `.env` on each machine.

## Runtime Memory Files

Files:

- `backend/.deer-flow/agents/research-analyst/memory.json`
- `backend/.deer-flow/users/default/agents/research-analyst/memory.json`

These files contain runtime memory state. They are useful for reproducing the
current local environment, but they are not required for the integration code
to work.

Recommended policy:

- commit shared agent `config.yaml` and `SOUL.md` only when you want the agent
  definition versioned;
- avoid committing per-user memory unless you intentionally want to seed or
  migrate memory;
- for MMKB users, rely on per `workspace + user` memory directories created at
  runtime.

## File-By-File Change Index

| File | Change meaning | Main purpose |
|---|---|---|
| `.deer-flow/agents/research-analyst/config.yaml` | shared local custom agent config | define tools/model/skill for research analyst |
| `.deer-flow/agents/research-analyst/SOUL.md` | shared local custom agent behavior | make local knowledge primary evidence |
| `.env` | local secret/config values | runtime provider keys and internal MMKB token; should not be public |
| `Makefile` | added `docker-restart-gateway` target | quick restart after Gateway/tool/config changes |
| `README.md` | added MMKB integration note | document proxy context/token handoff |
| `backend/.deer-flow/agents/research-analyst/config.yaml` | backend runtime agent config copy | container/backend-visible agent definition |
| `backend/.deer-flow/agents/research-analyst/SOUL.md` | backend runtime agent SOUL copy | container/backend-visible behavior prompt |
| `backend/.deer-flow/agents/research-analyst/memory.json` | runtime memory | local state; optional to version |
| `backend/.deer-flow/users/default/agents/research-analyst/config.yaml` | default-user agent config copy | legacy/default local runtime support |
| `backend/.deer-flow/users/default/agents/research-analyst/SOUL.md` | default-user SOUL copy | legacy/default local runtime support |
| `backend/.deer-flow/users/default/agents/research-analyst/memory.json` | default-user memory | local state; optional to version |
| `backend/CLAUDE.md` | added MMKB proxy integration note | future contributor context |
| `backend/app/gateway/authz.py` | added MMKB proxy run-create bypass | allow MMKB-authenticated runs without DeerFlow UI auth |
| `backend/app/gateway/services.py` | added MMKB context merge and runtime user resolution | workspace+user memory isolation |
| `backend/packages/harness/deerflow/config/agents_config.py` | fallback only requires user `config.yaml` | shared agent definition, per-user memory |
| `backend/packages/harness/deerflow/tools/custom/__init__.py` | custom tools package marker | import path for MMKB tools |
| `backend/packages/harness/deerflow/tools/custom/rag/__init__.py` | RAG tools package marker | import path for MMKB tools |
| `backend/packages/harness/deerflow/tools/custom/rag/tools.py` | seven MMKB RAG tools | authenticated local knowledge access |
| `backend/tests/test_custom_agent.py` | fallback tests | protect shared-agent/per-user-memory behavior |
| `config.yaml` | local runtime config | registers MMKB tools and model setup |
| `docker/docker-compose-dev.yaml` | removed empty token override | preserve `.env` internal auth token |
| `extensions_config.json` | disabled MCP extension skeleton | local extension config |
| `scripts/docker.sh` | load `.env`, mirror defaults, restart gateway command | reliable local Docker workflow |
| `skills/custom/local-deep-research/SKILL.md` | local research workflow skill | systematic MMKB document research |

## Deployment Guidance

Recommended deployment path:

1. Fork `bytedance/deer-flow` into your own GitHub account.
2. Keep the official repository as `upstream`.
3. Push this branch, usually `mmkb-integration`, to your fork.
4. Do not push real `.env` values.
5. On the target machine:

```bash
git clone git@github.com:<your-account>/deer-flow.git
cd deer-flow
git checkout mmkb-integration
cp .env.example .env
```

6. Fill target-machine `.env`.
7. Ensure MMKB and DeerFlow share the same `DEER_FLOW_INTERNAL_AUTH_TOKEN`.
8. Start DeerFlow:

```bash
make docker-start
```

If MMKB and DeerFlow run on different machines, update the MMKB-side
`deerflow_base_url` or deployment config so MMKB can reach DeerFlow Gateway, and
update each DeerFlow RAG tool `base_url` so DeerFlow can reach MMKB.

## Rebase / Upgrade Notes

When pulling new upstream DeerFlow changes, review these areas carefully:

- `backend/app/gateway/authz.py`: permission decorator/auth flow may change.
- `backend/app/gateway/services.py`: run creation and context merge may change.
- `backend/packages/harness/deerflow/config/agents_config.py`: agent path
  resolution may change.
- `backend/packages/harness/deerflow/tools/`: custom tool import paths may
  change.
- `docker/docker-compose-dev.yaml` and `scripts/docker.sh`: compose env and
  project-root handling may change.
- `config.yaml`: upstream config schema may change.

After rebase, verify:

```bash
make docker-restart-gateway
docker logs --tail 100 deer-flow-gateway
```

Then test from MMKB:

- `model=agent` starts a run without DeerFlow UI auth;
- RAG tools receive MMKB bearer and return document/search results;
- memory is written under the expected `mmkb-<workspace>-<user>` user bucket;
- no `401`, `403`, or CSRF errors appear in the MMKB/OpenWebUI path.
