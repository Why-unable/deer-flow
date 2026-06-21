# DeerFlow `config.yaml` 配置参考

本文说明当前 DeerFlow 主配置文件 `config.yaml` 能配置的内容、加载规则和主要
字段。字段定义以 `deerflow.config.app_config.AppConfig`、各配置模型以及应用层
实际读取逻辑为准；`config.example.yaml` 是可直接参考的完整示例。

## 1. 加载与生效规则

### 1.1 配置文件定位

配置文件按以下优先级查找：

1. 代码显式传入的 `config_path`；
2. 环境变量 `DEER_FLOW_CONFIG_PATH`；
3. 调用方项目根目录的 `config.yaml`；
4. 兼容旧目录结构的 `backend/config.yaml` 或仓库根目录 `config.yaml`。

运行数据目录默认是项目根目录下的 `.deer-flow/`，可通过 `DEER_FLOW_HOME`
覆盖。Skills 路径还可通过 `DEER_FLOW_SKILLS_PATH` 覆盖。

### 1.2 环境变量引用

任意字段值只要是以 `$` 开头的完整字符串，加载时都会递归解析为环境变量：

```yaml
api_key: $OPENAI_API_KEY
database:
  postgres_url: $DATABASE_URL
```

环境变量不存在时，配置加载直接失败。当前实现不支持
`${VAR:-default}` 形式，也不会替换字符串中间的 `$VAR`。

### 1.3 版本与升级

`config_version` 用于检测本地配置是否落后于 `config.example.yaml`。版本较旧时
启动日志会给出警告，可运行：

```bash
make config-upgrade
```

该命令用于合并示例配置新增字段。修改配置模式时应同步提高示例文件版本。

### 1.4 类型校验与扩展字段

核心配置使用 Pydantic 校验。`AppConfig`、`models[]`、`tools[]`、
`tool_groups[]` 和 `sandbox` 允许额外字段，以支持模型提供商、工具、沙箱和
应用层扩展参数。因此：

- 强类型字段会校验类型、枚举和数值范围；
- 提供商专属字段会原样传给对应实现；
- `uploads`、`channels` 等应用扩展段可存在于主配置中；
- 拼错的额外字段不一定会报错，应与本文及 `config.example.yaml` 对照。

配置对象带有基于文件路径和修改时间的缓存。Gateway 请求时读取的多数运行参数
可在下一次请求/消息中生效；数据库、checkpointer、stream bridge 等进程级组件
通常需要重启才能完整生效。

## 2. 顶层配置总览

| 配置段 | 用途 |
|---|---|
| `config_version` | 配置模式版本 |
| `log_level` | DeerFlow 与 app 日志级别 |
| `token_usage` | 模型 token 用量采集 |
| `models` | 可用聊天模型及提供商参数 |
| `tool_groups` / `tools` | 工具分组与工具注册 |
| `tool_search` | MCP 等工具的延迟发现 |
| `tool_output` | 大型工具输出外置与截断 |
| `loop_detection` | 重复工具调用循环检测 |
| `safety_finish_reason` | 拦截提供商安全终止后的不完整工具调用 |
| `uploads` | Gateway 上传限制与文档转换 |
| `sandbox` | 沙箱提供商、挂载、环境和输出限制 |
| `skills` / `skill_evolution` | Skill 存储、挂载和自主修改 |
| `title` | 会话标题生成 |
| `summarization` | 长会话上下文摘要 |
| `memory` | 跨会话长期记忆 |
| `agents_api` | 自定义 Agent 管理 API |
| `subagents` | 子 Agent 默认值、覆盖和自定义类型 |
| `acp_agents` | 外部 ACP Agent |
| `guardrails` | 工具调用前授权 |
| `circuit_breaker` | LLM 连续失败熔断 |
| `database` | LangGraph 与应用数据的统一持久化后端 |
| `checkpointer` | 旧版独立 LangGraph checkpoint 配置 |
| `run_events` | 消息与执行 trace 的事件存储 |
| `stream_bridge` | Agent worker 到 SSE 的事件桥 |
| `channels` | 飞书、Slack、Telegram、微信等 IM 接入 |

## 3. 基础与模型配置

```yaml
config_version: 11
log_level: info
token_usage:
  enabled: true
```

- `log_level` 默认 `info`，主要使用 `debug`、`info`、`warning`、`error`；
  只调整 `deerflow` 和 `app` 日志层级。
- `token_usage.enabled` 控制 token 用量中间件及 UI 用量展示。

### 3.1 `models`

```yaml
models:
  - name: primary
    display_name: Primary Model
    description: General-purpose model
    use: langchain_openai:ChatOpenAI
    model: gpt-4.1
    api_key: $OPENAI_API_KEY
    base_url: https://api.openai.com/v1
    request_timeout: 600
    max_retries: 2
    max_tokens: 8192
    temperature: 0.7
    supports_thinking: false
    supports_reasoning_effort: false
    supports_vision: true
```

标准字段：

| 字段 | 必填 | 含义 |
|---|---|---|
| `name` | 是 | DeerFlow 内唯一模型名；其他配置通过它引用 |
| `use` | 是 | 模型类导入路径，格式为 `module:Class` |
| `model` | 是 | 传给提供商的模型 ID |
| `display_name` / `description` | 否 | UI 展示信息 |
| `supports_thinking` | 否 | 是否允许开启 thinking |
| `supports_reasoning_effort` | 否 | 是否支持 reasoning effort |
| `supports_vision` | 否 | 是否启用图片理解链路 |
| `when_thinking_enabled` | 否 | thinking 开启时合并到模型参数的字典 |
| `when_thinking_disabled` | 否 | thinking 关闭时合并到模型参数的字典 |
| `thinking` | 否 | `when_thinking_enabled` 的快捷配置 |
| `use_responses_api` | 否 | OpenAI `ChatOpenAI` 是否走 Responses API |
| `output_version` | 否 | Responses API 的结构化输出版本 |

`api_key`、`base_url`、`max_tokens`、`temperature`、超时、重试以及其他字段属于
提供商参数，会原样传给 `use` 指向的模型类。不同提供商接受的字段不同。

## 4. 工具配置

```yaml
tool_groups:
  - name: web
  - name: file:read

tools:
  - name: web_search
    group: web
    use: deerflow.community.ddg_search.tools:web_search_tool
    max_results: 5
```

- `tool_groups[].name`：工具逻辑分组名，可带额外元数据。
- `tools[].name`：工具唯一名。
- `tools[].group`：所属分组。
- `tools[].use`：工具变量导入路径，格式为 `module:variable`。
- 其他字段作为工具提供商参数。

### 4.1 `tool_search`

```yaml
tool_search:
  enabled: false
```

启用后，MCP 工具不再全部直接进入模型上下文，而通过 `tool_search` 在运行时发现，
适合工具数量较多的部署。

### 4.2 `tool_output`

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `enabled` | `true` | 启用大型工具输出保护 |
| `externalize_min_chars` | `12000` | 超过该字符数时写入文件；`0` 禁用外置 |
| `preview_head_chars` / `preview_tail_chars` | `2000` / `1000` | 外置后保留的头尾预览 |
| `fallback_max_chars` | `30000` | 无法写盘时的最大输出；`0` 禁用回退截断 |
| `fallback_head_chars` / `fallback_tail_chars` | `8000` / `3000` | 回退截断保留头尾长度 |
| `storage_subdir` | `.tool-results` | thread outputs 下的保存目录 |
| `exempt_tools` | `read_file`, `read_file_tool` | 不参与输出保护的工具 |
| `tool_overrides` | `{}` | 按工具名覆盖 `externalize_min_chars` |

## 5. 运行保护

### 5.1 `loop_detection`

```yaml
loop_detection:
  enabled: true
  warn_threshold: 3
  hard_limit: 5
  window_size: 20
  max_tracked_threads: 100
  tool_freq_warn: 30
  tool_freq_hard_limit: 50
  tool_freq_overrides:
    bash:
      warn: 150
      hard_limit: 300
```

`warn_threshold` / `hard_limit` 控制相同工具调用集合的重复次数；
`tool_freq_*` 控制同类工具的累计调用频率。所有阈值至少为 `1`，hard limit
不能低于 warn threshold。

### 5.2 `safety_finish_reason`

```yaml
safety_finish_reason:
  enabled: true
  detectors:
    - use: my_package:CustomSafetyDetector
      config: {}
```

用于阻止提供商因安全策略终止生成后仍返回的不完整工具调用。`detectors` 不配置时
使用内置 OpenAI、Anthropic 和 Gemini 检测器；配置非空列表时完全覆盖内置集合。

### 5.3 `guardrails`

```yaml
guardrails:
  enabled: true
  fail_closed: true
  passport: null
  provider:
    use: deerflow.guardrails.builtin:AllowlistProvider
    config:
      denied_tools: [bash]
```

每次工具执行前调用授权提供商。`fail_closed: true` 表示提供商异常时拒绝工具调用。

### 5.4 `circuit_breaker`

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `failure_threshold` | `5` | 连续失败多少次后打开熔断器 |
| `recovery_timeout_sec` | `60` | 再次尝试恢复前等待秒数 |

## 6. 上传与沙箱

### 6.1 `uploads`

`uploads` 是应用层扩展配置，由 Gateway 和文件转换代码读取：

| 字段 | 示例默认值 | 含义 |
|---|---:|---|
| `max_files` | `10` | 单次上传最大文件数 |
| `max_file_size` | `52428800` | 单文件最大字节数 |
| `max_total_size` | `104857600` | 单次上传总字节数 |
| `auto_convert_documents` | `false` | 是否在后端宿主机自动转换 Office/PDF |
| `pdf_converter` | `auto` | `auto`、`pymupdf4llm` 或 `markitdown` |

自动转换会在沙箱隔离之前解析不可信文件，只有在可信上传场景中才应启用。

### 6.2 `sandbox`

```yaml
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: false
  mounts: []
  environment: {}
  bash_output_max_chars: 20000
  read_file_output_max_chars: 50000
  ls_output_max_chars: 20000
```

通用字段：

| 字段 | 含义 |
|---|---|
| `use` | 必填，沙箱提供商类导入路径 |
| `allow_host_bash` | LocalSandboxProvider 是否允许直接执行宿主机 bash |
| `mounts[]` | `host_path`、`container_path`、`read_only` 组成的额外挂载 |
| `environment` | 注入容器的环境变量 |
| `bash_output_max_chars` | bash 输出中间截断上限，`0` 禁用 |
| `read_file_output_max_chars` | 文件读取头部截断上限，`0` 禁用 |
| `ls_output_max_chars` | 列目录头部截断上限，`0` 禁用 |

AIO/Provisioner 沙箱还可使用 `image`、`port`、`replicas`、
`container_prefix`、`idle_timeout`、`provisioner_url` 等提供商扩展字段。
`LocalSandboxProvider` 不是安全隔离边界，`allow_host_bash` 只应用于完全可信环境。

## 7. Skill 与 Agent

### 7.1 `skills`

| 字段 | 默认值 | 含义 |
|---|---|---|
| `use` | `deerflow.skills.storage.local_skill_storage:LocalSkillStorage` | Skill 存储实现 |
| `path` | 项目根目录下 `skills` | 宿主机 Skill 路径 |
| `container_path` | `/mnt/skills` | 沙箱内挂载路径 |

### 7.2 `skill_evolution`

- `enabled`：是否允许 Agent 创建或修改 `skills/custom`；
- `moderation_model_name`：Skill 安全审查模型，`null` 使用主模型。

### 7.3 `agents_api`

`agents_api.enabled` 控制 Gateway 是否暴露自定义 Agent 的 SOUL、配置和用户画像管理
接口。默认关闭，应只在可信、经过认证的管理边界后开启。

### 7.4 `subagents`

```yaml
subagents:
  timeout_seconds: 900
  max_turns: null
  agents:
    general-purpose:
      timeout_seconds: 1800
      max_turns: 160
      model: primary
      skills: [web-search]
  custom_agents:
    analysis:
      description: Data analysis specialist
      system_prompt: Analyze data carefully.
      tools: [bash, read_file]
      disallowed_tools: [task, ask_clarification, present_files]
      skills: []
      model: inherit
      max_turns: 50
      timeout_seconds: 900
```

`agents` 覆盖内置或自定义子 Agent；`custom_agents` 声明新的可委派类型。
`skills: null` 表示继承，`skills: []` 表示不加载 Skill。

### 7.5 `acp_agents`

每个键声明一个外部 ACP Agent：

| 字段 | 必填 | 含义 |
|---|---|---|
| `command` | 是 | 启动 ACP 子进程的命令 |
| `description` | 是 | 能力说明 |
| `args` | 否 | 命令参数 |
| `env` | 否 | 注入子进程的环境变量 |
| `model` | 否 | 传给 ACP Agent 的模型提示 |
| `auto_approve_permissions` | 否 | 是否自动批准 ACP 权限请求，默认 `false` |

## 8. 对话辅助能力

### 8.1 `title`

| 字段 | 默认值 | 约束与含义 |
|---|---:|---|
| `enabled` | `true` | 自动生成标题 |
| `max_words` | `6` | `1..20` |
| `max_chars` | `60` | `10..200` |
| `model_name` | `null` | 标题模型，`null` 使用默认模型 |
| `prompt_template` | 内置模板 | 支持 `{max_words}`、`{user_msg}`、`{assistant_msg}` |

### 8.2 `summarization`

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `enabled` | `false` | 启用自动上下文摘要 |
| `model_name` | `null` | 摘要模型 |
| `trigger` | `null` | 一个或多个触发条件，满足任意条件即触发 |
| `keep` | `messages: 20` | 摘要后保留的最近上下文 |
| `trim_tokens_to_summarize` | `4000` | 送入摘要模型前的最大 token；`null` 不裁剪 |
| `summary_prompt` | `null` | 自定义摘要提示词 |
| `preserve_recent_skill_count` | `5` | 摘要时保留的最近 Skill 文件数 |
| `preserve_recent_skill_tokens` | `25000` | Skill 文件总保留预算 |
| `preserve_recent_skill_tokens_per_skill` | `5000` | 单个 Skill 文件保留上限 |
| `skill_file_read_tool_names` | `read_file/read/view/cat` | 判定为 Skill 文件读取的工具名 |

`trigger` 和 `keep` 的结构为 `{type, value}`，其中 `type` 可为：

- `messages`：消息数；
- `tokens`：token 数；
- `fraction`：模型最大输入上下文的比例。

### 8.3 `memory`

长期记忆的字段、数据流和隔离策略见
[`MEMORY_IMPLEMENTATION.md`](./MEMORY_IMPLEMENTATION.md)。主要字段为
`enabled`、`storage_path`、`storage_class`、`debounce_seconds`、
`model_name`、`max_facts`、`fact_confidence_threshold`、
`injection_enabled` 和 `max_injection_tokens`。

## 9. 持久化与事件流

### 9.1 `database`

```yaml
database:
  backend: sqlite
  sqlite_dir: .deer-flow/data
  postgres_url: ""
  echo_sql: false
  pool_size: 5
```

| 字段 | 含义 |
|---|---|
| `backend` | `memory`、`sqlite` 或 `postgres` |
| `sqlite_dir` | SQLite 文件目录，最终文件为 `{sqlite_dir}/deerflow.db` |
| `postgres_url` | PostgreSQL DSN，建议使用 `$DATABASE_URL` |
| `echo_sql` | 是否输出 SQL，适合调试 |
| `pool_size` | PostgreSQL 应用 ORM 连接池大小 |

配置文件未包含 `database` 时，`AppConfig.from_file()` 会应用
`sqlite + .deer-flow/data` 默认值。`memory` 后端重启后丢失数据；SQLite 适合单节点；
PostgreSQL 适合生产多节点。

### 9.2 `checkpointer`（兼容旧配置）

```yaml
checkpointer:
  type: sqlite
  connection_string: .deer-flow/checkpoints.db
```

`type` 可为 `memory`、`sqlite`、`postgres`。同时配置时，它只覆盖 LangGraph
checkpoint 后端，优先于 `database`；新部署建议只配置 `database`。

### 9.3 `run_events`

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `backend` | `memory` | `memory`、`db` 或 `jsonl` |
| `max_trace_content` | `10240` | DB trace 内容截断字节数 |
| `track_token_usage` | `true` | 是否累计 run token 用量 |

### 9.4 `stream_bridge`

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `type` | `memory` | 当前可配置 `memory` 或 `redis`；Redis 尚未实现 |
| `redis_url` | `null` | Redis URL，预留字段 |
| `queue_maxsize` | `256` | 每个 run 的内存事件缓冲上限 |

## 10. IM Channels

`channels` 是应用层扩展配置。通用字段：

- `langgraph_url`：LangGraph 兼容 Gateway API 地址；
- `gateway_url`：辅助 Gateway API 地址；
- `session`：默认 `assistant_id`、LangGraph `config` 和运行 `context`；
- 每个平台可覆盖 `session`，并可按用户覆盖；
- `DEER_FLOW_CHANNELS_LANGGRAPH_URL` 和 `DEER_FLOW_CHANNELS_GATEWAY_URL`
  可覆盖两个通用 URL。

支持的平台配置包括：

| 平台 | 主要字段 |
|---|---|
| `feishu` | `enabled`、`app_id`、`app_secret`、`domain` |
| `slack` | `enabled`、`bot_token`、`app_token`、`allowed_users` |
| `telegram` | `enabled`、`bot_token`、`allowed_users` |
| `wechat` | token、iLink、二维码登录、轮询、状态目录、文件大小与扩展名限制 |
| `wecom` | `enabled`、`bot_id`、`bot_secret` |
| `dingtalk` | `enabled`、`client_id`、`client_secret`、`allowed_users`、`card_template_id` |
| `discord` | `enabled`、`bot_token`、guild/channel 白名单、mention/thread 模式 |

Docker 中 Channel 运行在 Gateway 容器内时，`localhost` 指向容器自身；通常应使用
`http://gateway:8001/api` 和 `http://gateway:8001`。

## 11. 不在 `config.yaml` 中的配置

- MCP server 启用状态和 Skill 启用状态存放在 `extensions_config.json`；
- LangSmith、Langfuse tracing 当前通过环境变量配置；
- Gateway 外部认证使用其独立环境/应用配置；
- `.env` 负责保存密钥和供 `$VAR` 引用的值，不应提交到 Git。

## 12. 最小配置示例

```yaml
config_version: 11
log_level: info

models:
  - name: primary
    use: langchain_openai:ChatOpenAI
    model: gpt-4.1
    api_key: $OPENAI_API_KEY
    supports_vision: true

sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: false

memory:
  enabled: true
  injection_enabled: true

database:
  backend: sqlite
  sqlite_dir: .deer-flow/data
```

生产配置还应明确审查沙箱隔离、数据库后端、上传策略、工具授权、密钥管理和
Channel 网络地址。
