# DeerFlow 仓库 Agent 协作指南

> 本文件是 `AGENTS.md` 的中文镜像，便于阅读和审查。Agent 执行规则仍以
> `AGENTS.md` 为准；修改其中任一文件时，应同步检查并更新另一份文件。

## 开始工作前

当前 checkout 并非普通的上游 DeerFlow 克隆。它包含本地 MMKB 集成，使 MMKB
可以通过 OpenAI 兼容的 `model=agent` 路径，将 DeerFlow 作为独立 Agent
运行时调用。

修改代码前：

1. 阅读待修改区域最近一级的 `AGENTS.md` 和 `CLAUDE.md`。
2. 进行 MMKB 集成相关工作时，阅读：
   - `docs/MMKB_INTEGRATION_CHANGES.md`：当前实现改动清单。
   - `docs/MMKB_URL_LIFECYCLE.md`：RAG 资源链接行为。
   - `docs/MMKB_AGENT_STORAGE_AND_OOM_TROUBLESHOOTING.md`：存储配置、长时间
     SSE 和内存风险。
3. 编辑前检查当前工作区。本仓库可能存在正在进行的本地改动，不得还原或覆盖
   与当前任务无关的工作。

`docs/MMKB_INTEGRATION_CHANGES.md` 是 DeerFlow 中 MMKB 专项改动的事实来源，
必须与实际实现保持同步。

## 仓库边界

后端具有严格的依赖方向：

- `backend/packages/harness/deerflow/` 是可复用的 Agent 框架，不得导入
  `app.*`。
- `backend/app/` 是 Gateway 和应用层，可以导入 `deerflow.*`。
- `frontend/` 是 Next.js DeerFlow UI。
- `monitor/` 是可选运维面板，不属于 Gateway 请求链路。

Harness/App 边界由 `backend/tests/test_harness_boundary.py` 强制检查。

优先遵守现有代码归属边界，不要新增跨层辅助逻辑。通用 Agent/RAG 行为应放在
Harness 中，Gateway HTTP 路由和鉴权逻辑应放在 `backend/app/` 中。

## MMKB 集成不变量

MMKB 继续负责用户认证和 workspace 文档访问控制。DeerFlow 将
`mmkb_bearer_token` 视为不透明值，仅在调用 MMKB API 时原样重放。

必须保持以下不变量：

- MMKB 代理鉴权绕过仅限于创建 run。
- 运行时 memory 和 thread state 继续按 MMKB `workspace + user` 隔离。
- 委派的子 Agent 只能接收明确允许的 MMKB 鉴权和身份上下文。
- RAG 工具通过语义 client/service 分层访问 MMKB，不直接读取 MMKB 数据库或
  服务端文件系统。
- `tools.py` 负责 LangChain schema 和序列化，不负责构造 HTTP endpoint。
- `client.py` 负责当前 HTTP transport，并实现与 transport 无关的
  `MMKBClient` protocol。
- `service.py`、`assets.py` 和 `mmkb_links.py` 负责共享响应策略，必须可以被
  未来的 MCP transport 复用。
- HTTP 失败继续返回既有 JSON error 契约，不得意外以工具异常形式向外抛出。

相关实现区域：

```text
backend/packages/harness/deerflow/tools/custom/rag/
|-- context.py
|-- client.py
|-- service.py
|-- assets.py
|-- mmkb_links.py
`-- tools.py
```

## 用户可见链接规则

不得将 Agent 回复中的所有链接视为同一种链接：

- `document_url` 指向 `/documents/<uuid>`。它是 MMKB 浏览器页面，有意要求浏览器
  已登录，并且当前 workspace 与文档匹配。
- `image_url`、`video_url` 和 `video_thumbnail_url` 必须由 MMKB 签名，并以
  `/api/document-media/<token>` 返回，匿名聊天前端才能渲染。
- DeerFlow 生成的 `/mnt/user-data/outputs/...` 是内部路径。MMKB 会将其转换为
  签名的 `/api/agent/artifacts/<token>` 下载链接。
- `markdown_merged_path` 等 MMKB 服务端路径仅是元数据，不得传给 sandbox 文件
  工具，也不得作为用户可见链接输出。

MMKB 负责媒体签名以及签名密码学和过期校验。DeerFlow 阶段 4 只负责将剩余相对
URL 类字段补全为绝对地址并记录诊断信息；不得自行生成签名，也不得静默修复损坏
的签名 URL。

Agent、SOUL 文件和本地研究 skill 必须要求模型逐字复制 `rag_*` 结果中的用户
可见 URL。禁止根据 document ID 或 asset ID 构造链接。

修改链接行为时，验证完整链路：

1. MMKB 工具响应结构。
2. DeerFlow 阶段 4 处理。
3. 签名 URL 结构。
4. 最终 Assistant Markdown。
5. 环境允许时，执行等效于浏览器访问的真实请求。

## 资源可观测性

资源链接诊断必须有用，同时不得泄露凭据或签名 token。

- `mmkb_link_stage4`、`mmkb_tool_resource_validation` 和
  `assistant_resource_validation` 必须保持为仅包含计数的聚合日志。
- 可用时记录 `thread_id` 和 `run_id`，以便对比工具响应和最终 Assistant 输出。
- 不得记录完整 URL、bearer token、签名 token、document ID 或私有服务端路径。
- DeerFlow 只进行结构校验。它可以发现截断、token 格式错误、异常源站或未签名的
  受保护媒体；签名有效性、过期、鉴权和文件是否存在仍由 MMKB 负责。
- 工具层合法但在 Assistant 层变为非法的 URL，表示模型输出发生了改写或截断。

可选 monitor 服务读取聚合运行时诊断信息。使用 Docker Compose 的 `monitor`
profile 显式启动：

```bash
docker compose -p deer-flow-dev -f docker/docker-compose-dev.yaml \
  --profile monitor up -d monitor
```

服务绑定到 `127.0.0.1:9090`；远程访问通常需要 SSH 端口转发。Monitor 是可选
服务，未启用对应 profile 时不会启动。

## 文档维护策略

每次修改代码时，遵守根目录 `CLAUDE.md` 中的仓库级文档维护策略：

- 用户可见行为或安装配置变化时，更新 `README.md`。
- 架构、命令或开发流程变化时，更新相关 `CLAUDE.md`。
- 仓库规则变化时，保持 `AGENTS.md` 和 `AGENTS_ZH.md` 同步。

此外，只要改动影响 MMKB 集成，就必须更新
`docs/MMKB_INTEGRATION_CHANGES.md`，包括：

- Gateway 对 MMKB 代理请求的认证或授权。
- `mmkb_bearer_token`、`public_base_url`、MMKB 身份或运行时用户处理。
- MMKB RAG 工具、链接处理、资源校验或可观测性。
- `research-analyst` 配置/SOUL 或本地研究 skill。
- MMKB 相关工具注册、Docker 启动或 monitor 行为。

用户可见 RAG 资源链接的阶段或校验边界变化时，更新
`docs/MMKB_URL_LIFECYCLE.md`。

## 验证

每个功能或 bug 修复都必须包含相关自动化测试；无法自动测试时，必须说明原因。

开发过程中先运行与改动直接相关的最小检查。声明改动完成前，如果修改了共享契约、
运行时边界、认证、持久化或广泛使用的行为，必须运行完整的相关测试套件。对于范围
狭窄且隔离的改动，应运行所有直接受影响的检查，并说明未运行完整套件的剩余风险。

后端格式和 lint：

```bash
cd backend
uv run ruff check <changed paths>
uv run ruff format --check <changed paths>
```

MMKB 集成专项测试：

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

还应运行与改动边界匹配的测试：

- Gateway 鉴权/上下文改动：相关 Gateway 测试和 MMKB proxy 测试。
- Harness 架构改动：`tests/test_harness_boundary.py`。
- Memory 隔离改动：memory storage、middleware 和 custom-agent 测试。
- Docker/monitor 改动：渲染 Compose 配置并验证受影响服务健康。
- 前端改动：遵守 `frontend/AGENTS.md` 并运行相关 unit/E2E 检查。

能够执行真实请求时，不得仅依据 JSON 结构或单元测试宣称用户可见资源链接可用。

## 敏感文件和运行时文件

不得提交真实 secret。

- `.env` 必须仅保留在本地。
- 使用 `.env.example` 记录变量名和配置提示。
- `DEER_FLOW_INTERNAL_AUTH_TOKEN` 运行时必须与 MMKB 一致，但真实值不得出现在
  文档、日志或已提交文件中。
- 真实 bearer token、签名资源 token 和 secret 不得出现在测试、日志、文档或
  已提交文件中。测试可以使用明显虚构的占位值。

将 `backend/.deer-flow/**/memory.json`、thread 目录、生成的 artifact、日志和
monitor 输出视为运行时状态。只有明确需要初始化或迁移 memory 时，才提交运行时
memory。

## 同步上游

与 `bytedance/deer-flow` 同步时，优先采用全新上游对比和 3-way merge/patch
流程。不得使用上游目录树直接覆盖当前 checkout。

重新检查 `docs/MMKB_INTEGRATION_CHANGES.md` 中记录的 MMKB 集成区域，尤其是：

- `backend/app/gateway/authz.py`
- `backend/app/gateway/services.py`
- `backend/packages/harness/deerflow/config/agents_config.py`
- `backend/packages/harness/deerflow/tools/custom/rag/`
- `backend/packages/harness/deerflow/runtime/`
- `config.yaml`
- `scripts/docker.sh`
- `docker/docker-compose-dev.yaml`
- `monitor/`

解决上游变更后，验证 MMKB 仍可创建 `model=agent` run，委派 RAG 工具仍保留
workspace 范围的 bearer 上下文，资源链接仍然可用，artifact 下载仍能定位正确
运行时用户目录，并且 memory 仍按 `workspace + user` 隔离。
