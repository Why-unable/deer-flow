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

用户可见链接的完整生成、签名、鉴权、下载和排障说明见同级 MMKB 项目中的
`docs/LINK_DELIVERY.md`。DeerFlow 侧的 RAG 资源 URL 阶段划分、阶段 4
聚合日志和视觉资产两阶段读取说明见 `docs/MMKB_URL_LIFECYCLE.md`。

### 运行事件持久化

相关文件：

- `config.yaml`

MMKB 的 agent 模式可能产生较多 LLM、工具和子 Agent 运行事件。当前将
`run_events.backend` 配置为 `db`，把这些事件写入现有 DeerFlow 数据库，
避免 `memory` 后端在长期运行过程中把各 thread 的完整事件持续保留在
Gateway 进程内存中。

该设置与 checkpoint 共享 `database` 配置所指向的数据库，但使用不同的
数据表和用途：

- checkpoint 保存 LangGraph thread 的可恢复执行状态；
- run event 保存一次 run 的消息、工具结果、执行轨迹和 token 统计。

`max_trace_content: 10240` 只限制写入数据库的单条 trace 内容大小；
`track_token_usage: true` 保留各类 Agent 的 token 用量统计。

该配置只减少 run event 历史长期驻留在 Gateway 进程内存中的风险，不会自动
取消仍在执行的 Agent run。当前 MMKB Agent 请求已经使用
`stream_subgraphs=false` 限制子图消息流量，并发送
`on_disconnect=cancel`；如果 MMKB/客户端 SSE 中途断开，DeerFlow 会取消本轮
后台 run，避免无客户端消费的孤立任务继续执行。相关风险、取证方法和建议见
`docs/MMKB_AGENT_STORAGE_AND_OOM_TROUBLESHOOTING.md`。

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

### Memory 文件结构修复与运行时用户解析

相关文件：

- `backend/packages/harness/deerflow/agents/memory/storage.py`
- `backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py`
- `backend/tests/test_memory_storage.py`
- `backend/tests/test_memory_middleware_user_context.py`

用户级 `memory.json` 可能因旧版本、迁移或人工初始化而只包含 `{}`。
该内容虽然是合法 JSON，但缺少更新器要求的 `user`、`history` 和 `facts`
字段，会导致异步 memory 更新失败并持续保持空文件。

现在读取 memory 时会补齐缺失的标准结构，同时保留已有摘要、facts 和未知
扩展字段。`MemoryMiddleware` 也会优先从 LangGraph runtime context 解析
`user_id`，确保 MMKB 请求在后台 memory 更新阶段仍写入对应的
`mmkb-<workspace>-<user>` bucket，而不是回退到 `default`。

## 自定义 MMKB RAG 工具

DeerFlow 的 `rag_*` 工具调用 MMKB 时，会随 bearer 鉴权请求发送
`X-MMKB-Public-Base-URL`，其值来自本次 Agent run 的 `public_base_url`。
MMKB 据此将搜索结果和文档资源列表中的图片、视频及视频缩略图 URL 转换为
限时签名链接。Agent 必须逐字使用工具返回的 URL；外部聊天前端加载这些
媒体时不需要附带 MMKB bearer token。

`document_url` 不属于媒体签名范围，仍然指向需要 MMKB 浏览器登录会话和
workspace 权限的文档详情页面。

相关文件：

- `backend/packages/harness/deerflow/tools/custom/__init__.py`
- `backend/packages/harness/deerflow/tools/custom/rag/__init__.py`
- `backend/packages/harness/deerflow/tools/custom/rag/context.py`
- `backend/packages/harness/deerflow/tools/custom/rag/client.py`
- `backend/packages/harness/deerflow/tools/custom/rag/service.py`
- `backend/packages/harness/deerflow/tools/custom/rag/assets.py`
- `backend/packages/harness/deerflow/tools/custom/rag/mmkb_links.py`
- `backend/packages/harness/deerflow/tools/custom/rag/tools.py`
- `config.yaml`

在 `knowledge` tool group 下新增了 8 个自定义工具：

| 工具 | MMKB endpoint | 用途 |
|---|---|---|
| `rag_list_documents` | `GET /api/documents?status=ready&limit=N` | 发现 ready 状态文档 |
| `rag_search` | `GET /api/search?q=&mode=&limit=` | 搜索文本 chunk 和视觉资产 |
| `rag_get_document` | `GET /api/documents/<id>` | 读取单个文档元数据 |
| `rag_get_document_preview` | `GET /api/documents/<id>/preview` | 读取合并 markdown 预览 |
| `rag_get_document_chunks` | `GET /api/documents/<id>/chunks` | 检查已索引 chunk |
| `rag_get_document_assets` | `GET /api/documents/<id>/assets` | 返回紧凑视觉资产目录 |
| `rag_get_document_asset` | `GET /api/documents/<id>/assets` 后按 asset ID 精确筛选 | 读取一个资产的完整详情 |
| `rag_list_collections` | `GET /api/collections` | 检查 collection 层级 |

工具行为：

- `tools.py` 只保留 LangChain 工具 schema、参数校验、docstring、语义 service
  调用和最终 JSON 序列化，不再直接拼装 HTTP endpoint。
- 工具选择描述区分主题检索与清单发现：普通本地知识主题查询默认从
  `rag_search` 开始；`rag_list_documents` 用于文档清单、范围发现和多文档综述
  候选池，不作为普通主题查询的固定前置步骤。
- `context.py` 统一解析工具静态 `base_url/timeout/public_base_url_fallback` 与请求级
  `mmkb_bearer_token/public_base_url`。
- `context.py` 每次构造 MMKB 工具运行上下文时输出
  `mmkb_runtime_context` 聚合日志，记录公开地址来源
  `public_base_url_source=configurable|context|fallback_public_base_url|fallback_base_url`、
  `fallback_used`、bearer 是否存在和 thread/run 标识；日志不包含 bearer token
  或签名媒体 token。若出现 `public_base_url_source=fallback_public_base_url`，
  说明本次工具调用没有拿到 MMKB 代理传入的公开源站，但已使用工具静态公网
  保险丝；若出现 `fallback_base_url`，说明保险丝也缺失，用户可见链接可能
  退回到 Docker 内部 `base_url`。
- `client.py` 定义 transport-neutral 的语义 `MMKBClient` protocol；当前
  `HTTPMMKBClient` 负责把 `search`、`get_document_assets` 等方法映射为 HTTP
  endpoint，并保留现有 HTTP 错误 JSON 契约。
- `service.py` 在 transport 返回后统一应用阶段 4 链接处理和聚合日志；
  `rag_get_document` 会为 MMKB API 详情响应补充规范
  `document_url=/documents/<document_id>`，避免模型把
  `/api/documents/<document_id>` 详情 endpoint 当成用户可见文档页。
- `assets.py` 集中管理紧凑分页目录、caption 裁减和精确单资产筛选。
- `utils/mmkb_resource_validation.py` 对 MMKB 媒体 URL 执行不依赖签名密钥的结构
  校验，并统计误用的 `/api/documents/<id>` API 详情地址
  (`api_document_detail_urls`)；结构化工具结果中的 `md_asset_base` 作为 API 元数据
  基路径处理，不计为未签名媒体 URL；只记录计数和原因，不记录完整 URL、token
  或文档 ID。
- Base URL 来自每个工具的 `base_url` 配置，默认是
  `http://host.docker.internal:8000`，用于 Docker 容器访问宿主机上的 MMKB。
- runtime 中的 `public_base_url` 优先用于把返回 URL 绝对化。
- runtime 中的 `mmkb_bearer_token` 会作为 `Authorization` header。
- Gateway 合并 MMKB 代理传入的 run context 时输出
  `deerflow_run_context_merge` 日志，记录 `incoming_public_base_url_present`、
  合并后的 `configurable_public_base_url/context_public_base_url` 以及
  workspace/user 是否存在。该日志用于区分 MMKB 是否未传、Gateway 是否未合并、
  以及 RAG 工具是否在后续阶段回退。
- lead agent 使用 `task` 派发子 Agent 时，会从父运行时的
  `config.configurable` 和 `context` 中按白名单提取 `mmkb_bearer_token`、
  `public_base_url` 和 MMKB 身份上下文，传入子 Agent runtime，并同步写入子
  Agent 的 `RunnableConfig.configurable` 与 `RunnableConfig.context`；因此子 Agent 调用 `rag_*` 时工具可以继续
  读取同一 workspace 范围的鉴权和公网 base URL，不会因为 delegated run 丢失
  bearer 而返回 `401`，也不会退回 Docker 内部 `base_url` 生成用户可见链接。
  其他父运行时配置和 secret 不会被自动复制。
- HTTP 失败会作为 JSON error object 返回，而不是直接 raise。
- 相对的 `*_url`、`*_path`、`*_base` 字段会尽量转换为绝对 URL。
- 文档页 `document_url` 会统一归一为本轮 `public_base_url` 下的
  `/documents/<document_id>`；即使中间层出现 `host.docker.internal` 或
  `/api/documents/<document_id>`，也不会作为用户可见文档链接透出。
- DeerFlow 侧的响应链接转换集中在
  `backend/packages/harness/deerflow/tools/custom/rag/mmkb_links.py`。该模块保持
  MMKB 的资源签名职责不变，只负责阶段 4 绝对化和可观测性统计。
- 每次 `rag_*` 请求完成后会输出一条 `mmkb_link_stage4` 聚合日志，包含工具名、
  URL 字段数、绝对化字段数、触发比例、签名媒体数和仍然受保护的媒体数，不记录
  URL、bearer 或文档 ID。`protected_media_remaining` 正常应为 0。
- `MMKBService` 在每次工具响应处理后输出 `mmkb_tool_resource_validation`，携带可用的
  `thread_id/run_id`，并统计完整三段式签名、缺段、payload 编码异常、
  timestamp/signature 格式异常、漏签媒体、普通文档页 UUID 结构和预期源站。
- `RunJournal` 对包含 MMKB 资源 URL 的 lead agent 最终正文输出
  `assistant_resource_validation`，并持久化 `assistant.resource.validation` trace
  event。工具层正常而正文层异常表示模型在最终输出时改写、截断或虚构了 URL。
- 普通 `/documents/<uuid>` 页面仍依赖浏览器 session 和匹配的当前 workspace；
  `document_pages_require_session` 仅用于提示，`unexpected_document_origins` 或
  `malformed_document_pages` 才属于文档页链接结构失败。
- 这些校验不拥有 MMKB 签名密钥，只验证结构；签名密码学有效性、过期和目标文件
  是否存在仍由 MMKB 在实际资源请求时判断。
- `rag_get_document_assets` 在 DeerFlow 侧将 MMKB 全量资产响应投影为有界分页目录：
  默认每页 8 项、最多 10 项，保留完整签名 URL、asset/document/page/block 定位
  字段和最多 160 字的 `caption_preview`，删除服务端绝对路径、完整 metadata 和完整
  OCR，避免大型资产列表被工具输出预算外置后导致模型看不到中间项 URL。
- `rag_get_document_asset(document_id, asset_id)` 复用同一已鉴权 MMKB endpoint，
  在 DeerFlow 侧精确筛选单项，先返回独立 `media_urls` 清单，再返回完整 OCR、
  metadata 和字段。即使详情输出因体积过大被外置，签名 URL 仍处于模型可见头部。
  Agent 应先用资产目录发现候选，再用单资产详情确认准备展示的媒体。
- `rag_get_document_preview` 只提供文字上下文。工具返回前会移除 preview Markdown
  中的原始图片引用、`md_images/...` 相对路径、受保护的
  `/api/documents/<id>/media/...` 路径和原始 `IMG_META` 注释。若图片有
  alt、`page_id`、`block_id`、`asset_type`、`ocr.content` 或
  `orphan_text[].content`，工具会将这些白名单字段转成不含路径的纯文本图片说明；
  任何 `path`、`url`、`file`、`abs` 字段不输出，保留字段中出现的路径形态字符串
  也会替换为 `[路径已省略]`。返回中包含移除和说明保留计数。
  需要展示图片时必须改用 `rag_get_document_assets` 或
  `rag_get_document_asset` 取得签名 `image_url`。
- `rag_get_document_preview` 返回 `truncated=true` 时只表示已读取部分预览。
  对全文、整篇总结、方法、实验、结果、局限或其它全文级判断，Agent prompt、
  工具说明和本地 research skills 均要求优先读取 `rag_get_document_chunks`
  或用针对性 `rag_search` 补读后续章节；只有当前预览不足以建立文档概览时，
  才提高 `max_chars`，或使用上一轮返回的 `end_char` 作为 `start_char`
  继续读取下一段 preview。preview 窗口偏移基于清理后的 `preview_text`
  字符位置；若未补读，回答需说明证据范围。
- 工具 docstring 明确提示：MMKB 返回的 `markdown_merged_path` 等路径是
  API 元数据，不是 sandbox 内可读文件。Agent 不应把这些路径传给
  `read_file`、`grep` 或 `bash`。
- research agent 和本地研究 skills 要求面向用户的文档/图片链接只能逐字
  复制 `rag_*` 返回的 `document_url`、`image_url`，禁止根据
  `document_id` 手写或猜测链接，避免模型改坏 UUID 后产生不可用 URL。
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

该分层同时为未来 MCP 适配保留清晰边界，但当前 DeerFlow RAG 工具仍使用 HTTP。
如果未来增加 MCP transport，应实现同一组 `MMKBClient` 语义方法，并复用
`MMKBService`、`assets.py`、`mmkb_links.py` 和现有策略测试；不应让 MCP client
理解 REST path，也不应复制资产裁减或链接处理逻辑。

`config.yaml` 中的注册示例：

```yaml
tools:
  - name: rag_search
    group: knowledge
    use: deerflow.tools.custom.rag.tools:rag_search_tool
    base_url: http://host.docker.internal:8000
    timeout: 30
```

8 个 RAG 工具都采用同样的注册模式。`public_base_url_fallback` 仍是工具支持的
可选保险丝，但当前默认配置不写固定公网域名；正常情况下应由 MMKB 请求上下文
传入 `public_base_url`。

## MMKB Agent 输出适配

相关文件位于同级 MMKB 项目：

- `app/services/deerflow_agent_adapter.py`
- `app/services/chat_completion.py`
- `test/test_deerflow_agent_adapter.py`

MMKB 的 `model=agent` 模式消费 DeerFlow
`/api/threads/{thread_id}/runs/stream` SSE，并把 DeerFlow 事件转换成
OpenAI 兼容的 `chat.completion.chunk`：

- `messages` / `messages-tuple` 中的 assistant 正文转换为
  `delta.content`；
- 工具调用、工具结果、技能选择和子任务生命周期转换为 `delta.reasoning`；
- `values.artifacts` 中的新 artifact 路径转换为结构化的
  `[文件] 已生成` 下载入口；
- `custom` 事件中的 `task_started`、`task_running`、`task_completed`、
  `task_failed`、`task_cancelled` 和 `task_timed_out` 转换为简短中文状态行。

`task_running` 的进度行只使用 DeerFlow `task` 工具事件里的
`message_index`。这个值表示子 Agent 已产生第几条新的中间 AI 消息，不表示
真实业务阶段、文档处理序号或百分比进度。因此 MMKB 侧展示为：

```text
[子任务] 进行中：<description>（第 N 次进展更新）
```

这里的 “第 N 次进展更新” 是展示层的中间消息序号，不能用于判断任务是否已
完成第 N 个研究步骤。真实完成、失败、取消和超时仍以对应 terminal custom
event 以及 `task` 工具最终结果为准。

为了避免把子 Agent 的完整中间消息或完整结果泄露到思考过程，MMKB adapter
只输出状态摘要。`task_running` 会按 `task_id:message_index` 去重；
`task_completed` 只显示完成状态，不回显完整结果正文。

## DeerFlow Artifact 下载链接

DeerFlow 生成的报告、表格、Markdown 等文件位于 thread sandbox 的：

```text
/mnt/user-data/outputs/*
```

该路径不能由 MMKB/OpenAI 兼容客户端直接访问。完整签名和下载代理逻辑位于
同级 MMKB 项目的 `app/services/deerflow_artifacts.py`、
`app/services/deerflow_agent_adapter.py` 和 `app/services/chat_completion.py`；
DeerFlow 侧负责通过 `present_files` 把合法 outputs 路径写入 thread state 的
`artifacts` 列表，并通过 Gateway artifact API 提供文件。

当前存在两条用户可见输出路径：

1. `values.artifacts` 中出现新文件时，MMKB adapter 直接生成
   `[文件] 已生成：[filename](signed_url)`；
2. 如果模型正文包含 Markdown artifact 链接或裸
   `/mnt/user-data/outputs/*` 路径，MMKB 的流式改写器会等待可能跨 SSE chunk
   拆分的完整路径，再改写为签名下载 URL。

两条路径互相独立，因此同一个文件同时出现在 `values.artifacts` 和模型正文时，
当前可能展示两次下载入口。结构化 artifact 路径是稳定保底；正文流式改写负责
避免内部 `/mnt` 路径泄露和不可点击。若后续要求严格只展示一次，应按规范化后的
artifact 原始路径跨两条链路去重，并暂缓结构化 artifact 输出到流结束。

安全边界：

- 只有 `/mnt/user-data/outputs/*` 可以作为可下载 artifact；
- MMKB 生成的 token 绑定 DeerFlow base URL、thread、artifact 路径、
  workspace、user 和 runtime user bucket；
- MMKB 下载时使用 `X-DeerFlow-Internal-Token` 和
  `X-DeerFlow-Artifact-User` 定位到正确的 workspace+user 文件；
- Artifact 链接机制与 RAG 文档媒体签名是两套独立链路。

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
```

SOUL 行为：

- 当问题可以从 MMKB 回答时，优先使用本地知识；
- 对本地文档问题，在 web 工具前先使用 `rag_search`；
- 根据任务复杂度选择最短且充分的检索路径，证据充分时不为完成固定流程继续调用工具；
- 做出强断言前，检查文档元数据、preview、chunks 和 assets；
- 谨慎对待 OCR/caption 证据；
- 区分本地证据、外部网页上下文和推断；
- 对本地多文档综述、系统性文献综述、survey、annotated bibliography 或跨文档方法比较任务，使用 `local-systematic-literature-review`；
- 当前暂不启用 PPT/PPTX 生成；用户要求制作演示文稿时，可先提供 Markdown 版汇报提纲、讲稿、页面结构或素材清单，但不承诺生成 PPT/PPTX 文件；
- 面向 MMKB/OpenAI 兼容客户端的用户时，不引导用户直接上传到 DeerFlow、访问 `/mnt` 路径或到 `/mnt` 目录查找结果；需要用户提供知识库文档时，提示其先上传到当前 MMKB 工作区知识库并等待解析完成；
- 上述规则只限制用户交互文案，不限制 Agent 和 Skill 内部使用 `/mnt/user-data/workspace/`、运行时实际存在的 `/mnt/user-data/uploads/` 和 `/mnt/user-data/outputs/`；最终产物仍写入 outputs 并通过 `present_files` 暴露；
- 只有当研究任务能拆成独立维度时才使用 subagent；
- 对本地深度研究、多文档综述或其它会生成最终报告的 subagent 委派，要求每个
  subagent 把完整研究记录写入共享 workspace 中的 `research-notes/` 中间文件；
- 主 agent 在生成最终报告前必须用 `read_file` 读取这些中间文件，并以文件内容
  作为主要汇总输入，不能只依赖 `task` 返回摘要；
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

- 明确、简短的本地知识问答先使用一次 `rag_search`，证据充分时直接回答；
- 仅在片段缺少上下文、需要精确证据或视觉细节时继续读取 preview/chunks/assets；
- 如果 preview 返回 `truncated=true` 且问题需要全文级证据，继续读取 chunks、
  做针对性检索，或说明只基于已读取预览；仅在概览不足时提高 `max_chars`，
  或使用上一轮返回的 `end_char` 作为 `start_char` 继续读取下一段 preview；
- `rag_list_documents` 不作为普通主题查询的固定前置步骤；
- 除非用户明确要求文件交付，否则轻量问答不默认生成报告文件；
- 在需要进行重研究的本地文档回答前使用完整研究流程；
- 从宽泛的 `rag_search` 开始；
- 使用查询变体、别名、中英文术语和文档标题；
- 针对重要证据检查 preview/chunks/assets；
- 使用 `hit`、`from_chunk_ids`、`image_url`、`caption_or_ocr`
  和 asset id 处理视觉资产；
- 使用 subagent 生成深度报告时，subagent 完整结果写入
  `research-notes/<task-slug>.md`，主 agent 读取这些文件后再汇总；
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

- 明确要求基于本地知识库做系统性文献综述；
- 对本地多篇论文、标准、报告或白皮书做 survey；
- 生成 annotated bibliography；
- 比较多篇本地文档的方法、发现、局限；
- 分析本地文档集合中的研究趋势、共识、分歧和缺口。

主要流程：

1. 确认主题、文档范围、文档数量、输出格式和引用偏好；
2. 使用 `rag_list_documents`、多轮 `rag_search` 和必要的
   `rag_list_collections` 发现候选文档；
3. 用明确的纳入/排除标准筛选候选文档，避免把 chunk 当作文档重复计数；
4. 对纳入文档读取 `rag_get_document`、`rag_get_document_preview`；
   若 preview 返回 `truncated=true` 且该文档将支持全文级结论，补读
   `rag_get_document_chunks` 或使用针对性 `rag_search`；仅在概览不足时提高
   `max_chars`，或使用上一轮返回的 `end_char` 作为 `start_char` 继续读取
   下一段 preview；必要时读取 `rag_get_document_assets`；
5. 对每篇文档抽取统一字段，例如目的/问题、方法/框架、关键发现、
   建议、局限和本地证据；
6. 使用 subagent 批量抽取时，每个 batch 写入
   `research-notes/slr-batch-<n>.json`，主 agent 读取所有 batch 文件后再综合；
7. 跨文档综合 themes、共识、分歧、缺口和实践含义；
8. 保存完整报告到 `/mnt/user-data/outputs/local-slr-<topic>-<date>.md`，
   并通过 `present_files` 展示。

默认引用方式是链接优先的本地证据引用：

```text
[本地证据：<title>](<document_url>)；document_id=<id>；chunk=<chunk_id>；page=<page>
```

如果涉及视觉证据，使用：

```text
[视觉证据：<title>](<document_url>)；document_id=<id>；asset=<asset_id>；page=<page>
```

报告末尾的 References / Local Sources 使用 Markdown 链接陈列来源，例如：

```text
- [<title>](<document_url>) (`document_id=<id>`)
```

正文中列出具体本地文档标题、论文名或资料名时，也优先使用
`[文档标题](document_url)`；只概括领域、类别或数量时可以不加链接。

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

- model allowlist 包含 MMKB 网页端模型选择会传入的
  `doubao-seed-1-6-250615`、`doubao-seed-2-0-pro-260215`；
  Gateway 仍会拒绝不在
  `config.yaml` `models:` 中的 `context.model_name`；
- model provider 使用 `CHAT_COMPLETION_API_KEY` 或
  `MULTIMODAL_EMBED_API_KEY`；
- 自定义 MMKB RAG 工具注册到 `knowledge` group；
- skills path 默认使用项目内 `skills/`；
- sandbox/file/bash 工具是否可用由 agent config 决定。

`extensions_config.json` 添加了一个本地 MCP/extension 配置骨架，
其中 filesystem、GitHub 和 Postgres MCP server 默认禁用。

重要 git 说明：

- `config.yaml` 和 `extensions_config.json` 当前均已被 Git 跟踪；
- 不要把某次本地 `git status` 记录当作长期事实；合并或发布前应重新运行
  `git status --short config.yaml extensions_config.json` 确认实际变更；
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

### 可选 Docker 运行监控

相关文件：

- `monitor/server.py`
- `monitor/Dockerfile`
- `monitor/requirements.txt`
- `monitor/static/index.html`

`monitor/` 已作为 `docker/docker-compose-dev.yaml` 的显式 `monitor` profile
接入开发 Compose。它不会默认随 DeerFlow 启动；使用
`docker compose -p deer-flow-dev -f docker/docker-compose-dev.yaml --profile monitor up -d monitor`
启动，并通过 `http://localhost:9090` 访问。

当前能力：

- 通过 Docker socket 发现 Compose project/name 包含 DeerFlow 的运行中容器；
- 每秒调用 Docker stats，记录各容器最近 300 个内存数据点；
- 使用 FastAPI 提供容器列表、历史查询和 WebSocket 实时快照；
- 使用 Chart.js 页面展示当前内存、最近峰值和约 5 分钟趋势。
- 从 DeerFlow 容器日志中采集脱敏的 `mmkb_runtime_context`、
  `deerflow_run_context_merge`、`mmkb_tool_resource_validation` 和
  `assistant_resource_validation` 聚合事件，展示 `thread_id/run_id` 短标识、
  工具名、公开地址来源、媒体结构异常、文档页结构、源站异常和
  session/workspace 依赖计数；完整 `thread_id/run_id` 仅放在浏览器 tooltip，
  不展示或保存文档 ID、签名 token、bearer token。
- 开发 Gateway 会把应用日志重定向到共享的 `logs/gateway.log`，monitor 以只读
  方式增量读取该文件，同时保留 Docker stdout 采集作为补充。
- Docker stats 和日志读取通过 worker thread 执行，避免同步 Docker SDK 调用阻塞
  FastAPI 事件循环，导致监控首页或 API 间歇性超时。

当前限制：

- 资源事件只保留聚合计数和已有 run/thread/tool 上下文，不主动探测 MMKB 页面，
  因而不能确认浏览器当前 workspace 或实际 HTTP 状态；
- 历史数据仅保存在 monitor 进程内存，重启后丢失；
- 采集异常目前仍被静默忽略，后续应增加 monitor 自身的错误计数；
- 动态 sandbox 容器可能不符合当前名称/project 匹配规则；
- Docker socket 权限较高，因此不应在未设计访问控制时直接公开。

如继续规范化，应保持显式启用而不是默认生产服务，并逐步补充 CPU、working set/RSS、网络、
I/O、PIDs、restart/OOM、宿主机内存，以及 Gateway 的 active runs、SSE、
stream bridge 队列和工具错误等应用级指标。长期监控应优先接入
Prometheus/Grafana，而不是仅依赖进程内历史。

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

部署前可从 DeerFlow 根目录运行：

```bash
./scripts/check_deerflow_internal_auth.sh
```

该脚本默认检查当前 DeerFlow 的 `.env` 与同级 `../mmkb/.env`，并验证：

- 两侧均存在 `DEER_FLOW_INTERNAL_AUTH_TOKEN`，且指纹一致；
- MMKB `.env` 能被正常 source；
- 若本机存在运行中的 MMKB 进程，其实际环境已加载该 token；
- DeerFlow 的公开 `/health` 可访问时，受保护的 `/api/models` 也接受该 token。

检查通过后的结尾提示会根据 MMKB 实际运行状态变化：

- MMKB 已运行且进程已加载预期 token：明确提示无需重启；
- 未检测到 MMKB 进程：提示启动 MMKB；
- 检测到 MMKB 进程但无法确认其环境：提示重启以确保加载预期 token。

缺失 token 时可运行：

```bash
./scripts/check_deerflow_internal_auth.sh --fix
```

修复模式会从已有的一侧同步到缺失侧；双方都缺失时生成一个共享 token；
双方已有但不一致时拒绝自动覆盖。只有 `.env` 或运行进程实际使用的 token
发生变化时，才需要重启对应服务；已经加载正确 token 的 MMKB 无需重启。

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
| `backend/packages/harness/deerflow/agents/memory/storage.py` | 自动补全不完整的 memory JSON 结构 | 避免 `{}` 导致长期 memory 更新失败 |
| `backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py` | 从 runtime context 解析 memory user id | 后台更新保持 workspace+user 隔离 |
| `backend/packages/harness/deerflow/tools/builtins/task_tool.py` | 白名单提取父运行时的 MMKB 鉴权与身份上下文 | 子 Agent 的 RAG 工具继续使用同一 workspace 权限 |
| `backend/packages/harness/deerflow/subagents/executor.py` | 将白名单运行时值合并进 delegated run | 避免子 Agent 调用 MMKB 时因 bearer 丢失而 `401` |
| `backend/packages/harness/deerflow/tools/custom/__init__.py` | custom tools package marker | MMKB tools import path |
| `backend/packages/harness/deerflow/tools/custom/rag/__init__.py` | RAG tools package marker | MMKB tools import path |
| `backend/packages/harness/deerflow/tools/custom/rag/context.py` | MMKB 工具静态设置和请求级身份上下文解析 | 集中处理 bearer、public URL、base URL 和 timeout |
| `backend/packages/harness/deerflow/tools/custom/rag/client.py` | 语义 `MMKBClient` protocol 和当前 HTTP transport | 隔离 endpoint/HTTP 细节，为未来 MCP transport 保留替换边界 |
| `backend/packages/harness/deerflow/tools/custom/rag/service.py` | transport-neutral MMKB service 和兼容 helper | 在任意 client 返回后统一执行链接策略和日志 |
| `backend/packages/harness/deerflow/tools/custom/rag/assets.py` | 视觉资产响应策略 | 集中管理分页目录、字段裁减和精确单项筛选 |
| `backend/packages/harness/deerflow/utils/mmkb_resource_validation.py` | MMKB 资源 URL 结构校验 | 在工具响应和最终正文两层统计媒体截断、漏签、文档页格式和源站异常，不记录 URL、文档 ID 或 token |
| `backend/packages/harness/deerflow/tools/custom/rag/tools.py` | 8 个轻量 MMKB LangChain tools | 保持公开工具 schema、参数校验和 JSON 输出 |
| `backend/packages/harness/deerflow/tools/custom/rag/mmkb_links.py` | MMKB 响应链接规范化和阶段 4 聚合日志 | 集中管理绝对化规则并监测漏签媒体 |
| `backend/tests/test_mmkb_client.py` | runtime context、语义 client 和 HTTP endpoint 映射测试 | 保护分层边界、鉴权头和现有错误契约 |
| `backend/tests/test_mmkb_resource_validation.py` | MMKB 媒体 URL 结构校验测试 | 覆盖完整签名、截断 token、漏签媒体和日志脱敏 |
| `backend/tests/test_mmkb_asset_tools.py` | 视觉资产紧凑目录和精确详情工具测试 | 保护分页、字段裁减、完整 URL 和单项筛选行为 |
| `backend/tests/test_mmkb_links.py` | MMKB 阶段 4 链接处理测试 | 保护绝对化、漏签检测和无敏感内容聚合日志 |
| `backend/tests/test_mmkb_tools_contract.py` | 8 个工具的 service 委派与 schema 契约测试 | 防止重构或新增 transport 时改变公开工具行为 |
| `backend/tests/test_custom_agent.py` | fallback 测试 | 保护共享 agent/用户级 memory 行为 |
| `config.yaml` | 本地 runtime 配置 | 注册 MMKB tools，同步 MMKB 网页端可选模型 allowlist，并将 run events 持久化到数据库以控制 Gateway 内存增长 |
| `docker/docker-compose-dev.yaml` | 移除空 token override | 保留 `.env` 中的内部 auth token |
| `docs/deploy.md` | MMKB 集成版 DeerFlow 最简部署指南 | 说明 `.env`、内部认证检查和 Docker 启动步骤 |
| `docs/MMKB_AGENT_OUTPUT_COMPARISON.md` | DeerFlow 前端与 MMKB Agent Mode 输出对比 | 记录事件转换、Artifact 和通用 OpenAI 客户端展示边界 |
| `docs/MMKB_AGENT_STORAGE_AND_OOM_TROUBLESHOOTING.md` | 存储配置、SSE 未结束和 OOM 专项排查 | 记录存储配置边界、`on_disconnect`、stream bridge、事件体积和取证建议 |
| `docs/MMKB_URL_LIFECYCLE.md` | RAG URL 生命周期和视觉资产两阶段读取说明 | 区分媒体签名、阶段 4 绝对化、模型输出和 artifact 链路 |
| `docs/README.md` | DeerFlow 本地文档索引 | 区分当前说明、历史记录、专项审查和计划文档 |
| `extensions_config.json` | 禁用状态的 MCP extension skeleton | 本地 extension 配置 |
| `monitor/server.py`、`monitor/static/index.html`、`monitor/Dockerfile` | 可选 Compose 运行监控 | 本地观察容器内存趋势和脱敏 MMKB 资源校验事件 |
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
- `rag_get_document_assets` 默认目录页保持在工具输出外置阈值以内，并在
  `has_more=true` 时提供 `next_page`；
- `rag_get_document_asset(document_id, asset_id)` 返回的 `media_urls`
  位于详情响应头部，正文展示图片时逐字复制该 URL；
- Gateway 日志中的 `mmkb_link_stage4` 能统计阶段 4 触发比例，且正常响应的
  `protected_media_remaining=0`；
- lead agent 派发的子 Agent 也能使用 `rag_*`，且不会因 bearer 丢失返回
  `401`；
- memory 写入预期的 `mmkb-<workspace>-<user>` user bucket；
- 新生成的 `/mnt/user-data/outputs/*` 文件能通过 MMKB 签名 artifact 链接下载；
- MMKB/OpenWebUI 路径中没有 `401`、`403` 或 CSRF 错误。
