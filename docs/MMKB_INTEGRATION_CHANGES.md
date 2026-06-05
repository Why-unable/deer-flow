# MMKB 集成改动说明

本文档记录为了接入 MMKB 而在本地 DeerFlow 中做出的改动。
它用于后续开发、代码审查、部署，以及将本分支 rebase 到上游
`bytedance/deer-flow` 时作为依据。

## 总览

这次集成把 DeerFlow 变成 MMKB 的独立 agent runtime：

```text
OpenWebUI / OpenAI-compatible client
  -> MMKB /v1/chat/completions model=agent
  -> DeerFlow Gateway /api/threads/{thread_id}/runs/stream
  -> DeerFlow agent + custom RAG tools
  -> MMKB authenticated document/search APIs
```

MMKB 仍然负责用户和 workspace 鉴权。DeerFlow 接收一个来自 MMKB
内部代理的 run 请求，把原始 MMKB bearer token 当作不透明值保存，
只在调用 MMKB 工具时重放这个 token。

本次集成的主要目标：

- 通过 MMKB 的 OpenAI 兼容 `model=agent` 模式暴露 DeerFlow；
- 让 DeerFlow 通过带鉴权的 HTTP 工具搜索和读取 MMKB 本地知识库；
- 保持 agent 定义共享，同时按 `workspace + user` 隔离 memory；
- 通过自定义 agent 和 skill 保留本地文档研究、本地多文档综述能力；
- 让后端、工具、配置改动后的本地 Docker 重启和开发流程更方便。

## 鉴权与身份

### Gateway 内部代理放行

相关文件：

- `backend/app/gateway/authz.py`
- `backend/app/gateway/services.py`
- `backend/CLAUDE.md`

MMKB 先鉴权外部客户端，然后调用 DeerFlow Gateway，并传入：

- `config.configurable.mmkb_bearer_token`：原始 MMKB
  `Bearer <workspace_id>:<api_key>` token；
- `context.public_base_url`：面向用户可访问的 MMKB base URL，用于生成可见链接；
- `context.mmkb_workspace_id`、`context.mmkb_user_id`、
  `context.mmkb_tenant_id`：MMKB 已鉴权后的身份元数据；
- `X-DeerFlow-Internal-Token`：共享内部密钥；
- 匹配的 CSRF header/cookie 对。

`authz.py` 新增 `_is_mmkb_proxy_run_create(...)`。当请求体中包含语法上有效的
`mmkb_bearer_token` 时，只允许 `resource="runs"` 且 `action="create"`
的请求通过。DeerFlow 不解析、不验证这个 token；后续由 MMKB 工具调用
MMKB API 时再验证。

`services.py` 新增：

- 将 `public_base_url`、`mmkb_workspace_id`、`mmkb_user_id`、
  `mmkb_tenant_id` 加入 context/configurable 允许列表；
- `resolve_mmkb_proxy_user(...)`，把 MMKB 身份映射为路径安全的
  DeerFlow runtime user id：

```text
mmkb-<workspace_id>-<user_id>
```

这个 user id 会在创建 run 期间写入 DeerFlow runtime user context，
随后在 `finally` 块中重置。

目的：

- MMKB 可以在不依赖 DeerFlow UI session auth 的情况下启动 DeerFlow run。
- DeerFlow 的 memory/checkpoint 行为可以按 MMKB 的 `workspace + user` 隔离。
- MMKB API 鉴权仍然是文档访问权限的最终依据。

重要边界：

- 这个 bypass 是刻意收窄的：它只允许创建 run。
- 如果转发的 bearer token 无效、过期或不再有权限，工具调用仍然会收到
  MMKB `401/403` 并失败。

## 共享 Agent 定义，隔离 Memory

相关文件：

- `backend/packages/harness/deerflow/config/agents_config.py`
- `backend/tests/test_custom_agent.py`

在这次修改前，只要用户级 agent 目录存在于
`.deer-flow/users/<user>/agents/<agent>/`，即使该目录里只有 `memory.json`，
也可能阻止 DeerFlow fallback 到共享 agent 定义。

现在 `resolve_agent_dir(...)` 只有在以下文件存在时，才把用户级 agent
视为真正存在：

```text
users/<user>/agents/<agent>/config.yaml
```

如果用户目录只包含 `memory.json`，DeerFlow 会 fallback 到共享/全局 agent
config 和 SOUL。

目的：

- agent 定义全局共享；
- 每个 MMKB `workspace + user` 拥有独立 memory；
- 删除或创建用户级 memory 目录时，不需要为每个用户复制完整 agent config。

`backend/tests/test_custom_agent.py` 中新增测试，验证：

- 当用户目录只有 `memory.json` 时，config 会 fallback；
- 同样条件下 SOUL 也会 fallback。

## 自定义 MMKB RAG 工具

相关文件：

- `backend/packages/harness/deerflow/tools/custom/__init__.py`
- `backend/packages/harness/deerflow/tools/custom/rag/__init__.py`
- `backend/packages/harness/deerflow/tools/custom/rag/tools.py`
- `config.yaml`

在 `knowledge` tool group 下新增了 7 个自定义工具：

| 工具 | MMKB endpoint | 用途 |
|---|---|---|
| `rag_list_documents` | `GET /api/documents?status=ready&limit=N` | 发现 ready 状态文档 |
| `rag_search` | `GET /api/search?q=&mode=&limit=` | 搜索文本 chunk 和视觉资产 |
| `rag_get_document` | `GET /api/documents/<id>` | 读取单个文档元数据 |
| `rag_get_document_preview` | `GET /api/documents/<id>/preview` | 读取合并 markdown 预览 |
| `rag_get_document_chunks` | `GET /api/documents/<id>/chunks` | 检查已索引 chunk |
| `rag_get_document_assets` | `GET /api/documents/<id>/assets` | 检查已抽取视觉资产 |
| `rag_list_collections` | `GET /api/collections` | 检查 collection 层级 |

工具行为：

- Base URL 来自每个工具的 `base_url` 配置，默认是
  `http://host.docker.internal:8000`，用于 Docker 容器访问宿主机上的 MMKB。
- runtime 中的 `public_base_url` 优先用于把返回 URL 绝对化。
- runtime 中的 `mmkb_bearer_token` 会作为 `Authorization` header。
- HTTP 失败会作为 JSON error object 返回，而不是直接 raise。
- 相对的 `*_url`、`*_path`、`*_base` 字段会尽量转换为绝对 URL。
- 工具 docstring 明确提示：MMKB 返回的 `markdown_merged_path` 等路径是
  API 元数据，不是 sandbox 内可读文件。Agent 不应把这些路径传给
  `read_file`、`grep` 或 `bash`。
- `research-analyst` SOUL、`local-deep-research` 和
  `local-systematic-literature-review` 也显式强化了同一约束：本地知识库
  文档内容只能通过 `rag_*` 工具读取，禁止把 MMKB 返回的服务端路径传给
  `grep`、`read_file`、`bash`、`ls` 等文件/命令工具。
- MMKB 下载 DeerFlow artifacts 时会在内部请求中同时发送
  `X-DeerFlow-Internal-Token` 和 `X-DeerFlow-Artifact-User`。后者只在内部
  token 校验通过且路径是 artifact 路由时生效，用于把下载请求定位到
  `mmkb-<workspace_id>-<user_id>` 用户桶，而不是默认的 `default` 用户桶。

目的：

- DeerFlow 不需要直接访问数据库或文件系统，也能把 MMKB 作为本地知识源。
- agent 侧检索沿用同一套 MMKB bearer 鉴权。
- 可通过公开 `image_url` 使用视觉资产。
- MMKB/OpenWebUI 可以下载由 workspace+user 隔离 run 生成的
  `/mnt/user-data/outputs/*` 文件。

`config.yaml` 中的注册示例：

```yaml
tools:
  - name: rag_search
    group: knowledge
    use: deerflow.tools.custom.rag.tools:rag_search_tool
    base_url: http://host.docker.internal:8000
    timeout: 30
```

7 个 RAG 工具都采用同样的注册模式。

## Research Analyst Agent

相关文件：

- `.deer-flow/agents/research-analyst/config.yaml`
- `.deer-flow/agents/research-analyst/SOUL.md`
- `backend/.deer-flow/agents/research-analyst/config.yaml`
- `backend/.deer-flow/agents/research-analyst/SOUL.md`
- `backend/.deer-flow/users/default/agents/research-analyst/config.yaml`
- `backend/.deer-flow/users/default/agents/research-analyst/SOUL.md`

`research-analyst` 自定义 agent 被配置为以本地知识为基础的研究助手。

当前配置：

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
  - local-systematic-literature-review
  - ppt-generation
```

SOUL 行为：

- 当问题可以从 MMKB 回答时，优先使用本地知识；
- 对本地文档问题，在 web 工具前先使用 `rag_search`；
- 做出强断言前，检查文档元数据、preview、chunks 和 assets；
- 谨慎对待 OCR/caption 证据；
- 区分本地证据、外部网页上下文和推断；
- 对本地多文档综述、系统性文献综述、survey、annotated bibliography 或跨文档方法比较任务，使用 `local-systematic-literature-review`；
- 对明确的 PPT/PPTX 生成请求，可使用公开版 `ppt-generation` skill，将结果写入 `/mnt/user-data/outputs/` 并通过 `present_files` 暴露为可下载 artifact；
- 使用 `ppt-generation` 生成中间计划时，必须把完整 plan JSON 放进回答正文，不能只保存到当前 thread 的 workspace 文件；如果下一轮上下文里没有完整 plan JSON，只看到“已保存 plan 文件”之类文字，应要求用户重新粘贴 plan 或重新生成；
- 只有当研究任务能拆成独立维度时才使用 subagent；
- 除非用户另有要求，否则使用中文输出。

为什么存在多份拷贝：

- 根目录 `.deer-flow/agents/...` 表示项目根目录下的本地 agent 状态。
- `backend/.deer-flow/agents/...` 是 backend/container runtime 位置。
- `backend/.deer-flow/users/default/...` 保留默认用户 runtime 拷贝，用于本地测试。

维护说明：

- 优先把共享定义保存在全局 `agents/` 路径下。
- 避免把完整 agent 定义复制到每个 MMKB 用户目录。用户级目录通常只应保存 memory。

## Local Deep Research Skill

相关文件：

- `skills/custom/local-deep-research/SKILL.md`

这个 skill 定义了本地知识库问题的研究流程。

它的边界是普通本地深度研究：回答一个具体问题、解释一个主题、
分析某个概念/系统/文档集，或生成基于本地证据的研究回答。
如果用户明确要求系统性文献综述、survey、annotated bibliography、
多篇论文/报告的跨文档方法比较、纳入/排除筛选或证据矩阵，应使用
`local-systematic-literature-review`。

主要指导：

- 在需要进行重研究的本地文档回答前加载该 skill；
- 从宽泛的 `rag_search` 开始；
- 使用查询变体、别名、中英文术语和文档标题；
- 针对重要证据检查 preview/chunks/assets；
- 使用 `hit`、`from_chunk_ids`、`image_url`、`caption_or_ocr`
  和 asset id 处理视觉资产；
- 只有当本地证据不足时，才把 web search 作为有限外部背景；
- 输出具备来源意识、明确证据边界的最终回答。

目的：

- 防止 agent 把本地 RAG 当成一次性 lookup；
- 让本地文档研究系统化、可复现；
- 改进对图、表、截图和 OCR 等视觉证据的处理。
- 避免与本地系统性文献综述场景混用。

## Local Systematic Literature Review Skill

相关文件：

- `skills/custom/local-systematic-literature-review/SKILL.md`

这个 skill 是公开版 `systematic-literature-review` 的本地知识库适配版。
它保留系统性综述的结构化方法，但不访问 arXiv，也不调用
`arxiv_search.py`；事实来源限定为 MMKB 本地知识库。

它和 `local-deep-research` 的区别是：`local-deep-research` 用于围绕一个
具体问题做本地深度研究；`local-systematic-literature-review` 用于构建
多文档集合、筛选来源、抽取统一字段并做跨文档主题综合。

适用场景：

- 基于本地知识库做系统性文献综述；
- 对本地多篇论文、标准、报告或白皮书做 survey；
- 生成 annotated bibliography；
- 比较多篇本地文档的方法、发现、局限；
- 分析本地文档集合中的研究趋势、共识、分歧和缺口。

主要流程：

1. 确认主题、文档范围、文档数量、输出格式和引用偏好；
2. 使用 `rag_list_documents`、多轮 `rag_search` 和必要的
   `rag_list_collections` 发现候选文档；
3. 用明确的纳入/排除标准筛选候选文档，避免把 chunk 当作文档重复计数；
4. 对纳入文档读取 `rag_get_document`、`rag_get_document_preview`，
   必要时读取 `rag_get_document_chunks` 和 `rag_get_document_assets`；
5. 对每篇文档抽取统一字段，例如目的/问题、方法/框架、关键发现、
   建议、局限和本地证据；
6. 跨文档综合 themes、共识、分歧、缺口和实践含义；
7. 保存完整报告到 `/mnt/user-data/outputs/local-slr-<topic>-<date>.md`，
   并通过 `present_files` 展示。

默认引用方式是本地证据引用：

```text
[本地证据：<title>, document_id=<id>, chunk=<chunk_id>, page=<page>]
```

如果涉及视觉证据，使用：

```text
[视觉证据：<title>, document_id=<id>, asset=<asset_id>, page=<page>]
```

目的：

- 将公开版系统综述 skill 的严谨结构迁移到本地知识库；
- 避免本地综述退化成单次检索或逐篇摘要；
- 强制保留纳入/排除标准、证据矩阵和跨文档综合；
- 避免把本地文件伪装成 arXiv/APA/IEEE 正式文献。

## 根配置与扩展配置

相关文件：

- `config.yaml`
- `extensions_config.json`

`config.yaml` 是完整的本地 runtime 配置。与集成相关的部分包括：

- model provider 使用 `CHAT_COMPLETION_API_KEY`；
- 自定义 MMKB RAG 工具注册到 `knowledge` group；
- skills path 默认使用项目内 `skills/`；
- sandbox/file/bash 工具是否可用由 agent config 决定。

`extensions_config.json` 添加了一个本地 MCP/extension 配置骨架，
其中 filesystem、GitHub 和 Postgres MCP server 默认禁用。

重要 git 说明：

- 仓库 `.gitignore` 忽略 `config.yaml` 和 `extensions_config.json`。
- 它们当前作为本地集成文件被 staged。
- 是否提交到私有 fork 需要明确决定。如果提交，它们会成为可部署的
  MMKB 集成版 DeerFlow 状态的一部分。

## Docker 与本地启动

相关文件：

- `Makefile`
- `scripts/docker.sh`
- `docker/docker-compose-dev.yaml`
- `README.md`

改动：

- 新增 `make docker-restart-gateway`。
- 新增 `scripts/docker.sh restart-gateway`。
- `scripts/docker.sh` 现在会在运行 Docker Compose 前 source 项目根目录 `.env`，
  让 compose 变量替换和 `env_file` 看到一致的值。
- 为本地/受限网络开发加入默认镜像源：
  - `APT_MIRROR=mirrors.ustc.edu.cn`
  - `UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple`
  - `UV_HTTP_TIMEOUT=120`
  - `NPM_REGISTRY=https://registry.npmmirror.com`
  - `UV_IMAGE=ghcr.io/astral-sh/uv:0.7.20`
- gateway 镜像构建会把 `UV_HTTP_TIMEOUT` 作为 build arg 传给
  `uv sync`，避免迁移到网络较慢机器后因 uv 默认 30 秒下载超时而构建失败；
  可在 DeerFlow 根目录 `.env` 或执行命令前覆盖该值。
- gateway 开发容器启动时还会通过 `dev-entrypoint.sh` 再次运行
  `uv sync --all-packages`；compose 会把 `UV_INDEX_URL` 和
  `UV_HTTP_TIMEOUT` 同时注入运行中容器，避免镜像构建成功后 gateway
  仍因启动阶段依赖同步失败而未监听 8001，进而导致 nginx 返回 502。
- Python 默认镜像使用阿里云 PyPI；部分云服务器无法连接 USTC PyPI
  镜像时，可避免 gateway 构建在依赖索引请求阶段直接失败。
- 从 gateway compose environment 中移除了显式的
  `DEER_FLOW_INTERNAL_AUTH_TOKEN=${...:-}`，避免它用空字符串覆盖
  `.env` / `env_file` 里的值。
- README 增加了简短的 MMKB 集成说明。

常用命令：

```bash
make docker-start
make docker-restart-gateway
make docker-logs-gateway
```

以下改动后使用 `docker-restart-gateway`：

- Gateway auth/services 代码；
- 自定义 RAG 工具；
- `config.yaml`；
- 内部 token / 环境变量 wiring。

## 环境变量

相关文件：

- `.env`

当前本地 `.env` 包含以下变量名：

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

用途：

- model/tool provider keys；
- MMKB 到 DeerFlow Gateway 的共享内部 token。

安全说明：

- 不要把真实 `.env` 值提交到公开仓库。
- 即使是私有 fork，提交 `.env` 仍然有风险；除非该仓库被明确当成私有部署包，
  否则也应避免。
- 推荐提交只包含变量名的 `.env.example`，并在每台目标机器上创建真实 `.env`。
- `DEER_FLOW_INTERNAL_AUTH_TOKEN` 必须与 MMKB 中配置的值一致。

当前仓库提醒：

- `.env` 被 `.gitignore` 忽略。
- 推送到 GitHub 前，运行：

```bash
git status --short
git restore --staged .env
```

如果 `.env` 已进入 git 历史或被跟踪，从 tracking 中移除：

```bash
git rm --cached .env
```

然后在每台机器上保留本地专用 `.env`。

## Runtime Memory 文件

相关文件：

- `backend/.deer-flow/agents/research-analyst/memory.json`
- `backend/.deer-flow/users/default/agents/research-analyst/memory.json`

这些文件包含 runtime memory 状态。它们有助于复现当前本地环境，
但不是集成代码正常工作所必需的。

推荐策略：

- 只有当你希望版本化 agent 定义时，才提交共享 agent 的 `config.yaml`
  和 `SOUL.md`；
- 避免提交用户级 memory，除非你明确想要 seed 或迁移 memory；
- 对 MMKB 用户，依赖 runtime 中按 `workspace + user` 自动创建的 memory 目录。

## 逐文件改动索引

| 文件 | 改动含义 | 主要目的 |
|---|---|---|
| `.deer-flow/agents/research-analyst/config.yaml` | 共享本地自定义 agent config | 定义 research analyst 的工具、模型和 skill |
| `.deer-flow/agents/research-analyst/SOUL.md` | 共享本地自定义 agent 行为 | 让本地知识成为主要证据 |
| `.env` | 本地 secret/config 值 | runtime provider keys 和内部 MMKB token；不应公开 |
| `Makefile` | 新增 `docker-restart-gateway` target | Gateway/tool/config 改动后快速重启 |
| `README.md` | 新增 MMKB 集成说明 | 记录 proxy context/token 交接 |
| `backend/.deer-flow/agents/research-analyst/config.yaml` | backend runtime agent config 拷贝 | 容器/backend 可见的 agent 定义 |
| `backend/.deer-flow/agents/research-analyst/SOUL.md` | backend runtime agent SOUL 拷贝 | 容器/backend 可见的行为 prompt |
| `backend/.deer-flow/agents/research-analyst/memory.json` | runtime memory | 本地状态；可选是否版本化 |
| `backend/.deer-flow/users/default/agents/research-analyst/config.yaml` | default-user agent config 拷贝 | legacy/default 本地 runtime 支持 |
| `backend/.deer-flow/users/default/agents/research-analyst/SOUL.md` | default-user SOUL 拷贝 | legacy/default 本地 runtime 支持 |
| `backend/.deer-flow/users/default/agents/research-analyst/memory.json` | default-user memory | 本地状态；可选是否版本化 |
| `backend/CLAUDE.md` | 新增 MMKB proxy 集成说明 | 给后续贡献者提供上下文 |
| `backend/app/gateway/authz.py` | 新增 MMKB proxy run-create bypass | 允许 MMKB 已鉴权 run 在无 DeerFlow UI auth 下创建 |
| `backend/app/gateway/services.py` | 新增 MMKB context merge 和 runtime user 解析 | workspace+user memory 隔离 |
| `backend/packages/harness/deerflow/config/agents_config.py` | fallback 只要求用户级 `config.yaml` 存在 | 共享 agent 定义、用户级 memory |
| `skills/public/ppt-generation/SKILL.md` | 增加 MMKB/OpenWebUI 多轮计划规则 | plan JSON 必须回显到正文，避免依赖跨 thread 文件 |
| `backend/packages/harness/deerflow/tools/custom/__init__.py` | custom tools package marker | MMKB tools import path |
| `backend/packages/harness/deerflow/tools/custom/rag/__init__.py` | RAG tools package marker | MMKB tools import path |
| `backend/packages/harness/deerflow/tools/custom/rag/tools.py` | 7 个 MMKB RAG tools | 带鉴权的本地知识访问 |
| `backend/tests/test_custom_agent.py` | fallback 测试 | 保护共享 agent/用户级 memory 行为 |
| `config.yaml` | 本地 runtime 配置 | 注册 MMKB tools 和模型配置 |
| `docker/docker-compose-dev.yaml` | 移除空 token override | 保留 `.env` 中的内部 auth token |
| `extensions_config.json` | 禁用状态的 MCP extension skeleton | 本地 extension 配置 |
| `scripts/docker.sh` | 加载 `.env`、默认镜像源、gateway restart 命令 | 可靠的本地 Docker 工作流 |
| `skills/custom/local-deep-research/SKILL.md` | 本地研究 workflow skill | 系统化 MMKB 文档研究 |
| `skills/custom/local-systematic-literature-review/SKILL.md` | 本地系统性文献综述 workflow skill | 基于 MMKB 多文档做 SLR、survey 和 annotated bibliography |

## 部署建议

推荐部署路径：

1. 将 `bytedance/deer-flow` fork 到你自己的 GitHub 账号。
2. 保留官方仓库作为 `upstream`。
3. 将本分支推送到你的 fork，通常是 `mmkb-integration`。
4. 不要推送真实 `.env` 值。
5. 在目标机器上：

```bash
git clone git@github.com:<your-account>/deer-flow.git
cd deer-flow
git checkout mmkb-integration
cp .env.example .env
```

6. 填写目标机器的 `.env`。
7. 确保 MMKB 和 DeerFlow 使用相同的 `DEER_FLOW_INTERNAL_AUTH_TOKEN`。
8. 启动 DeerFlow：

```bash
make docker-start
```

如果 MMKB 和 DeerFlow 运行在不同机器上，需要更新 MMKB 侧的
`deerflow_base_url` 或部署配置，让 MMKB 能访问 DeerFlow Gateway；
同时更新每个 DeerFlow RAG 工具的 `base_url`，让 DeerFlow 能访问 MMKB。

## Rebase / 升级注意事项

拉取新的上游 DeerFlow 改动时，需要重点检查这些区域：

- `backend/app/gateway/authz.py`：permission decorator / auth flow 可能变化。
- `backend/app/gateway/services.py`：run creation 和 context merge 可能变化。
- `backend/packages/harness/deerflow/config/agents_config.py`：agent path
  resolution 可能变化。
- `backend/packages/harness/deerflow/tools/`：custom tool import path 可能变化。
- `docker/docker-compose-dev.yaml` 和 `scripts/docker.sh`：compose env 和
  project-root 处理可能变化。
- `config.yaml`：上游 config schema 可能变化。

rebase 后验证：

```bash
make docker-restart-gateway
docker logs --tail 100 deer-flow-gateway
```

然后从 MMKB 测试：

- `model=agent` 能在没有 DeerFlow UI auth 的情况下启动 run；
- RAG 工具能收到 MMKB bearer 并返回 document/search 结果；
- memory 写入预期的 `mmkb-<workspace>-<user>` user bucket；
- MMKB/OpenWebUI 路径中没有 `401`、`403` 或 CSRF 错误。
