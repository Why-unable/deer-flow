# Hermes Agent 记忆模块实现说明

本文基于当前代码实现说明 Hermes Agent 记忆模块的职责边界、数据流、
存储结构、注入策略、外部 provider 插件机制、生命周期钩子和管理入口。

Hermes 的记忆系统不是单一组件，而是两层机制叠加：

1. 内置的、文件持久化的 curated memory：`MEMORY.md` 与 `USER.md`。
2. 可选的外部 memory provider 插件：Honcho、Mem0、Supermemory、
   Hindsight、Holographic、OpenViking、Retaindb、Byterover 等。

这两层可以同时存在。内置记忆始终是轻量、可审计、由模型主动调用工具维护的
稳定事实；外部 provider 则通过统一抽象接入检索、自动同步、会话结束抽取、
压缩前抽取和专属工具。

## 1. 记忆、会话和检索的区别

Hermes 中存在几类容易混淆的持久化信息：

| 类型 | 用途 | 主要存储 | 是否自动进入提示词 |
|---|---|---|---|
| 内置长期记忆 | 保存用户画像、偏好、环境事实、项目约定、工具经验 | `$HERMES_HOME/memories/MEMORY.md` 与 `USER.md` | 是，作为会话开始时的冻结快照 |
| 外部 memory provider | 接入第三方或本地记忆后端，提供召回、写入、总结、检索工具 | provider 自己的后端，例如 SQLite、云服务、向量库、API | 部分进入系统提示词，部分按轮次动态注入 |
| SessionDB 会话记录 | 保存真实对话消息、系统提示词、标题、父子 session 等 | Hermes SQLite session store | 否，但可通过 `session_search` 工具检索 |
| Context compression | 压缩长上下文，保留当前会话可继续执行的摘要 | 新 session 记录与压缩摘要消息 | 作为当前会话上下文继续使用 |
| Todo / skill / context files | 任务状态、技能、项目约束等专门结构 | 各自文件或 DB | 按各自规则注入 |

内置长期记忆不是完整聊天记录，也不是任务日志。它只保留短小、长期有效、
可复用的信息。真实历史对话由 SessionDB 负责，需要时通过 `session_search`
查询；临时任务状态不应该写入 memory。

## 2. 核心模块

| 模块 | 职责 |
|---|---|
| `tools/memory_tool.py` | 内置 memory 工具与 `MemoryStore`，负责 `MEMORY.md` / `USER.md` 的读写、预算、去重、安全扫描、原子写入 |
| `agent/agent_init.py` | 根据配置初始化内置 `MemoryStore` 和外部 `MemoryManager`，并把外部 provider 的工具 schema 加入 agent 工具列表 |
| `agent/system_prompt.py` | 组装系统提示词，将内置 memory 冻结快照和外部 provider 静态提示块放入 volatile tier |
| `agent/conversation_loop.py` | 每轮开始通知 provider、预取外部记忆、在当前用户消息上临时注入召回上下文、维护 memory nudge 计数 |
| `agent/tool_executor.py` | 路由内置 `memory` 工具调用；路由外部 provider 工具；把内置 memory 写入桥接给外部 provider |
| `agent/memory_provider.py` | 定义外部 memory provider 抽象基类和生命周期契约 |
| `agent/memory_manager.py` | 统一管理外部 provider：注册、初始化、预取、同步、工具路由、会话边界、压缩前钩子、写入镜像、安全 fencing |
| `plugins/memory/__init__.py` | 发现与加载内置和用户安装的 memory provider 插件 |
| `hermes_cli/memory_setup.py` | `hermes memory setup/status` 配置入口，发现 provider、安装依赖、写入配置 |
| `hermes_cli/web_server.py` | Dashboard memory API：查看 provider、切换 provider、重置内置 memory 文件 |
| `agent/conversation_compression.py` | 压缩前触发 provider 抽取，压缩导致 session_id 轮换时通知 provider 切换会话 |
| `run_agent.py` | 对外暴露 session 边界方法：同步外部记忆、提交记忆会话、关闭 provider |

## 3. 配置入口

默认配置位于 `hermes_cli/config.py` 的 `DEFAULT_CONFIG["memory"]`：

```yaml
memory:
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 2200
  user_char_limit: 1375
  provider: ""
```

字段含义：

| 字段 | 含义 |
|---|---|
| `memory_enabled` | 是否启用内置 `MEMORY.md` 注入和 `memory` target |
| `user_profile_enabled` | 是否启用内置 `USER.md` 注入和 `user` target |
| `memory_char_limit` | `MEMORY.md` 总字符预算，默认 2200 |
| `user_char_limit` | `USER.md` 总字符预算，默认 1375 |
| `provider` | 外部 memory provider 名称；空字符串表示只使用内置文件记忆 |

`agent/agent_init.py` 会读取这些配置。若 `skip_memory=True`，内置 store 和外部
provider 都不会初始化。这常用于子 agent、后台审查、curator、cron 或其他不应该
污染用户记忆的运行上下文。

## 4. 完整数据流

下面的树展示 Hermes memory 在一次 agent 生命周期中的主要路径。

```text
Hermes Agent memory 系统
├── 启动与配置
│   ├── 读取 config.yaml 的 memory 配置
│   ├── skip_memory=false
│   │   ├── 初始化内置 MemoryStore
│   │   │   ├── 读取 $HERMES_HOME/memories/MEMORY.md
│   │   │   ├── 读取 $HERMES_HOME/memories/USER.md
│   │   │   ├── 去重
│   │   │   ├── 扫描注入/泄露威胁
│   │   │   └── 捕获本会话冻结快照
│   │   └── memory.provider 非空
│   │       ├── 创建 MemoryManager
│   │       ├── plugins.memory.load_memory_provider(provider)
│   │       ├── provider.is_available()
│   │       ├── manager.add_provider(provider)
│   │       ├── manager.initialize_all(session_id, platform, hermes_home, user_id...)
│   │       └── 将 provider 工具 schema 追加到 agent.tools
│   └── skip_memory=true
│       └── 跳过所有 memory 初始化
│
├── 系统提示词构建
│   ├── stable tier
│   │   └── agent 身份、行为规则、固定工具指导
│   ├── context tier
│   │   └── AGENTS.md、SOUL.md、上下文文件等会话稳定内容
│   └── volatile tier
│       ├── MEMORY.md 冻结快照
│       ├── USER.md 冻结快照
│       ├── 外部 provider system_prompt_block()
│       └── 会话开始日期、session_id、model、provider
│
├── 每一轮用户消息
│   ├── 维护 memory nudge 计数
│   │   ├── 达到运行时 nudge_interval（未配置时默认为 10）
│   │   └── 提醒模型回顾是否需要写入 memory
│   ├── manager.on_turn_start(turn_number, original_user_message)
│   ├── manager.prefetch_all(original_user_message)
│   │   ├── 各 provider 返回相关召回文本
│   │   ├── 失败只记录 debug，不阻塞主流程
│   │   └── 本轮缓存一次，避免每个 tool iteration 重复查询
│   ├── API-call-time 临时注入
│   │   ├── build_memory_context_block(prefetch_result)
│   │   ├── 包裹在 <memory-context> fence 中
│   │   └── 追加到当前用户消息副本，不写入会话历史
│   ├── LLM 工具循环
│   │   ├── 内置 memory 工具
│   │   │   ├── add / replace / remove
│   │   │   ├── 持久写入 MEMORY.md 或 USER.md
│   │   │   └── add / replace 桥接 manager.on_memory_write(...)
│   │   └── 外部 provider 工具
│   │       └── manager.handle_tool_call(...)
│   └── 完成响应
│       ├── manager.sync_all(original_user_message, final_response, messages)
│       └── manager.queue_prefetch_all(original_user_message)
│
├── 会话边界
│   ├── CLI 退出、gateway session 过期、/reset 等真实边界
│   │   ├── manager.on_session_end(messages)
│   │   └── manager.shutdown_all()
│   ├── /new、context compression 等 session_id 轮换
│   │   ├── commit_memory_session(messages)
│   │   ├── manager.on_session_end(messages)
│   │   └── manager.on_session_switch(new_session_id, parent_session_id, ...)
│   └── 上下文压缩前
│       └── manager.on_pre_compress(messages)
│
└── 管理入口
    ├── hermes memory setup
    │   ├── 发现 provider
    │   ├── 选择 provider
    │   ├── 安装 pip 依赖
    │   ├── provider.post_setup 或 schema-based setup
    │   └── 写入 config.yaml / .env
    ├── Dashboard /api/memory
    │   ├── 查看 active provider
    │   ├── 查看 provider 列表
    │   └── 查看内置 memory 文件大小
    ├── Dashboard /api/memory/provider
    │   └── 修改 memory.provider
    └── Dashboard /api/memory/reset
        └── 删除 MEMORY.md / USER.md
```

## 5. 内置记忆：`MemoryStore`

内置记忆由 `tools/memory_tool.py` 实现，核心类是 `MemoryStore`。

### 5.1 两个 store

| target | 文件 | 语义 | 默认预算 |
|---|---|---|---|
| `memory` | `$HERMES_HOME/memories/MEMORY.md` | agent 的个人笔记：环境事实、项目约定、工具经验、长期可复用的教训 | 2200 字符 |
| `user` | `$HERMES_HOME/memories/USER.md` | 用户画像：身份、偏好、沟通风格、工作习惯、明确纠正 | 1375 字符 |

文件中的条目用分隔符 `\n§\n` 连接。条目可以是多行文本，但整个文件必须能按
该分隔符 round-trip，否则写入时会被视为外部漂移。

### 5.2 冻结快照模式

`MemoryStore.load_from_disk()` 会同时维护两份状态：

| 状态 | 用途 | 是否随工具写入即时变化 |
|---|---|---|
| `memory_entries` / `user_entries` | 工具操作使用的 live state | 是 |
| `_system_prompt_snapshot` | 注入系统提示词的冻结快照 | 否 |

这样设计的原因是 prefix cache。系统提示词在一个会话中尽量保持字节稳定。
如果模型在第 3 轮调用 `memory(add)` 写入了新偏好，文件会立刻落盘，工具响应也会
展示最新 live state，但当前会话的系统提示词不会被中途改写。下一次新会话或系统
提示词失效重建时，才会重新读取磁盘并捕获新的快照。

`agent/system_prompt.py::invalidate_system_prompt()` 在上下文压缩后会清空缓存，并重新
调用 `load_from_disk()`，因此压缩边界是内置记忆快照刷新点之一。

### 5.3 系统提示词渲染

内置记忆通过 `MemoryStore.format_for_system_prompt(target)` 注入。
渲染格式包含：

```text
══════════════════════════════════════════════
MEMORY (your personal notes) [67% — 1,474/2,200 chars]
══════════════════════════════════════════════
entry 1
§
entry 2
```

`USER.md` 的标题是 `USER PROFILE (who the user is)`。标题中的百分比和字符数让模型
知道容量压力，从而在需要写入时先合并、替换或删除旧条目。

### 5.4 工具动作

内置工具 schema 名称是 `memory`，支持三个动作：

| action | 行为 |
|---|---|
| `add` | 向目标 store 追加新条目 |
| `replace` | 用 `old_text` 短唯一子串定位条目，再替换为 `content` |
| `remove` | 用 `old_text` 短唯一子串定位条目并删除 |

没有 `read` action。当前可见记忆来自系统提示词快照；写入失败时工具响应会返回
当前条目列表；Dashboard 也可查看内置文件大小。

`replace` 和 `remove` 使用子串匹配：

- 没有匹配：返回错误。
- 匹配多个不同条目：返回预览并要求更具体的 `old_text`。
- 匹配多个完全相同条目：操作第一个。

### 5.5 写入安全

每次写入内置记忆会经过以下保护：

1. 内容为空时拒绝。
2. `add` 和 `replace` 会调用共享威胁扫描器，使用 strict scope 检测提示注入、
   凭据外泄、后门指令、不可见字符等风险。
3. `add` 会拒绝精确重复条目。
4. 写入前在目标文件对应的 `.lock` 文件上加排他锁。
5. 锁内重新读取磁盘，合并其他并发会话已经写入的内容。
6. 检测外部漂移：
   - 文件 parse 后 re-serialize 与原文不一致；
   - 单条 entry 超过整个 store 字符上限。
7. 若发现漂移，保存 `.bak.<timestamp>` 备份并拒绝写入，避免覆盖手工编辑、
   patch 工具或并发会话写出的非标准内容。
8. 检查字符预算。
9. 写入同目录临时文件，`fsync` 后用 `atomic_replace()` 原子替换目标文件。

读取不需要加锁，因为原子替换保证读者看到的是旧完整文件或新完整文件。

### 5.6 注入安全

`load_from_disk()` 在构建系统提示词快照时会再次扫描每条 entry。若某条 entry 命中
威胁模式，快照中不会注入原文，而是替换成类似：

```text
[BLOCKED: MEMORY.md entry contained threat pattern(s): ... Removed from system prompt; ...]
```

live state 保留原始内容，这样用户和 agent 仍能通过工具响应或文件检查发现并删除
问题条目。当前源码中的 placeholder 文案还保留了 `memory(action=read)` 的提示，
但工具 schema 实际只暴露 `add`、`replace`、`remove`；因此实际排查时通常直接查看
文件或通过后续工具错误响应中的 entries 列表确认内容。快照层替换可以防止磁盘上
已经存在的有害 memory 在会话启动时进入系统提示词。

## 6. 内置记忆何时写入

Hermes 不在后台自动总结每轮对话到 `MEMORY.md`。内置 memory 是“模型主动调用工具”
的 curated memory。

写入触发来自两类机制：

1. 工具 schema 的行为指导：`MEMORY_SCHEMA["description"]` 明确要求模型在用户纠正、
   明确要求记住、表达偏好、暴露长期环境事实或项目约定时主动调用 `memory`。
2. turn-based nudge：`agent/conversation_loop.py` 按运行时
   `_memory_nudge_interval` 维护计数。该值从 `memory.nudge_interval` 读取，
   未配置时默认为 10；达到间隔后提醒模型回顾是否有值得保存的内容。

因此，内置 memory 的写入不是“所有聊天自动抽取”，而是“由模型判断后调用工具，
受字符预算和安全扫描约束的人工可审计条目”。

## 7. 外部 provider 抽象

外部 provider 统一继承 `agent.memory_provider.MemoryProvider`。核心方法如下：

| 方法 | 触发时机 | 目的 |
|---|---|---|
| `is_available()` | agent 初始化前 | 判断依赖、凭据、配置是否具备 |
| `initialize(session_id, **kwargs)` | agent 初始化时 | 建立连接、创建资源、记录 session/user/profile 作用域 |
| `system_prompt_block()` | 系统提示词构建时 | 返回静态 provider 提示或状态 |
| `prefetch(query, session_id="")` | 每轮 API 调用前 | 返回当前轮相关召回内容 |
| `queue_prefetch(query, session_id="")` | 每轮完成后 | 后台预热下一轮可能需要的召回 |
| `sync_turn(user_content, assistant_content, messages=None)` | 每轮完成后 | 将完成的用户/助手回合写入 provider |
| `get_tool_schemas()` | agent 初始化后 | 暴露 provider 专属工具 |
| `handle_tool_call(tool_name, args)` | 模型调用 provider 工具时 | 执行检索、写入、删除等 provider 动作 |
| `shutdown()` | 真实会话边界 | flush 队列、关闭连接 |

可选钩子包括：

| 钩子 | 用途 |
|---|---|
| `on_turn_start(turn_number, message, **kwargs)` | provider 维护轮次、cadence 或按会话更新状态 |
| `on_session_end(messages)` | 会话结束时做总结、抽取、批量提交 |
| `on_session_switch(new_session_id, ...)` | `/resume`、`/branch`、`/reset`、`/new`、压缩等切换 session_id 时刷新 provider 内部状态 |
| `on_pre_compress(messages)` | 上下文压缩前从即将丢弃的消息中抽取记忆 |
| `on_memory_write(action, target, content, metadata=None)` | 内置 `memory(add/replace)` 成功调用时，把写入镜像到外部 provider |
| `on_delegation(task, result, child_session_id="")` | 父 agent 观察子 agent 委派结果 |
| `get_config_schema()` | 供 `hermes memory setup` 生成配置向导 |

外部 provider 应当把长延迟操作放到后台队列中。`prefetch()` 应尽量快速返回缓存结果，
因为它在每轮主模型调用前执行。

## 8. `MemoryManager` 的职责

`agent/memory_manager.py` 是外部 provider 的唯一运行时编排点。

### 8.1 注册限制

`MemoryManager` 允许内置名为 `builtin` 的 provider 和最多一个外部 provider。
如果第二个外部 provider 被注册，会被拒绝并记录 warning。

这个限制用于避免：

- 工具 schema 膨胀；
- 多个记忆后端同时写入造成冲突；
- 多个 provider 把同一事实以不同格式注入提示词；
- 每轮 prefetch 成本不可控。

当前 `agent/agent_init.py` 实际只根据 `memory.provider` 加载一个外部 provider。

### 8.2 失败隔离

`MemoryManager` 对 provider 的几乎所有调用都包在 `try/except` 中。
设计原则是：外部记忆是增强能力，不能阻塞主对话。

| 调用 | 失败处理 |
|---|---|
| `system_prompt_block()` | warning 后跳过该 provider |
| `prefetch()` / `queue_prefetch()` | debug 后跳过 |
| `sync_turn()` | warning 后继续 |
| `handle_tool_call()` | 返回 JSON tool error |
| 生命周期钩子 | debug 或 warning 后继续 |

### 8.3 工具路由

外部 provider 的 `get_tool_schemas()` 会返回 OpenAI function-calling schema。
`MemoryManager.add_provider()` 会建立 `tool_name -> provider` 索引。

执行时：

1. `agent/tool_executor.py` 先处理内置 `memory` 工具。
2. 若工具名不是内置工具，但 `agent._memory_manager.has_tool(function_name)` 为 true，
   则调用 `agent._memory_manager.handle_tool_call(function_name, args)`。
3. provider 返回 JSON 字符串作为工具结果。

工具名冲突时，先注册的 provider 保留工具，后注册 provider 的同名工具被忽略。

## 9. 外部记忆召回与注入

外部 provider 的动态召回不直接写入系统提示词，而是在当前轮用户消息的 API 副本上
临时追加。

执行顺序：

1. `conversation_loop` 保存 `original_user_message`，避免使用带 skill 注入的消息。
2. 调用 `manager.on_turn_start(...)`，让 provider 更新轮次状态。
3. 调用 `manager.prefetch_all(original_user_message)`。
4. 将返回文本缓存到 `_ext_prefetch_cache`，本轮 tool loop 复用。
5. 在构造 `api_messages` 时，仅对当前用户消息副本追加注入内容。
6. 原始 `messages` 列表不变，所以不会写入 SessionDB，也不会污染用户原文。

注入内容会经过 `build_memory_context_block()`：

```text
<memory-context>
[System note: The following is recalled memory context, NOT new user input. Treat as authoritative reference data — this is the agent's persistent memory and should inform all responses.]

provider returned context
</memory-context>
```

这样做有三个目的：

1. 明确告诉模型该内容是 recalled memory，不是用户新输入。
2. 用 fence 限定边界，降低 provider 返回内容越界影响主消息的风险。
3. 配合流式输出 scrubber，避免 provider 或模型把 memory context 原样泄露给用户界面。

`sanitize_context()` 会移除 provider 输出中已经带有的 `<memory-context>` 标签或内部
system note。如果 provider 返回预包裹内容，会被剥离并记录 warning。

## 10. 流式输出中的 memory context 清理

`StreamingContextScrubber` 是一个跨 delta 的状态机。它处理普通正则无法处理的情况：
`<memory-context>` 开始标签可能在一个 streaming chunk 中，结束标签在另一个 chunk 中。

行为：

- 未进入 span 时，寻找位于块边界的 `<memory-context>`。
- 进入 span 后丢弃所有内容直到 `</memory-context>`。
- 对可能是半个标签的尾部保留到下一个 chunk 再判断。
- 流结束时，如果 span 未闭合，则丢弃剩余内容。

这样即使模型错误地复述了 hidden memory fence，也尽量不让记忆上下文泄露到 UI。

## 11. 每轮同步与下一轮预取

完成一轮响应后，`run_agent.py::_sync_external_memory_for_turn()` 会把已完成回合同步给
外部 provider：

```text
manager.sync_all(original_user_message, final_response, session_id, messages)
manager.queue_prefetch_all(original_user_message, session_id)
```

该方法只在以下条件满足时执行：

- 有 `_memory_manager`；
- 当前轮没有被中断；
- 有 final response；
- 有原始用户消息。

被中断的轮次会完全跳过。这避免把用户没看到的半截回复、失败工具链或 reset 前的
不稳定状态写入长期记忆。

`sync_all()` 会检查 provider 的 `sync_turn` 签名。如果 provider 支持 `messages`
参数，就传入完整 OpenAI-style 消息列表；旧 provider 只接收 user/assistant 字符串。

## 12. 内置写入到外部 provider 的桥接

内置 `memory` 工具和外部 provider 并不是两套完全隔离的系统。

当模型调用：

```text
memory(action="add" 或 "replace", target="memory/user", content="...")
```

`agent/tool_executor.py` 会在内置写入后调用：

```text
manager.on_memory_write(action, target, content, metadata=...)
```

`MemoryManager` 会跳过名为 `builtin` 的 provider，然后把这次写入通知给外部 provider。
这使 Honcho、Supermemory、Holographic 等后端可以镜像内置 curated memory。

`remove` 不会桥接。删除语义在不同后端中可能需要 id、scope 或向量删除策略，简单传
一段 `old_text` 容易误删。当前桥接只覆盖新增和替换。

metadata 通常来自 `agent._build_memory_write_metadata(...)`，包含 task、tool call、
session 等上下文。`MemoryManager` 会兼容三类 provider 签名：

- `on_memory_write(action, target, content, metadata=...)`
- `on_memory_write(action, target, content, metadata)`
- 旧式 `on_memory_write(action, target, content)`

## 13. 会话切换、压缩和关闭

外部 provider 通常缓存 session_id、document_id、回合缓冲区或后台队列。因此 Hermes
在会话边界显式通知 provider。

### 13.1 真实会话结束

`run_agent.py::shutdown_memory_provider(messages)` 用于 CLI 退出、gateway session 过期、
`/reset` 等真实边界：

1. `manager.on_session_end(messages)`
2. `manager.shutdown_all()`

provider 可在 `on_session_end` 中做最终抽取或批量提交，在 `shutdown` 中 flush 队列。

### 13.2 session_id 轮换但 provider 继续运行

`run_agent.py::commit_memory_session(messages)` 会触发：

1. `manager.on_session_end(messages)`
2. 不调用 `shutdown_all()`

它用于 `/new`、context compression 等场景：旧 session 应该被抽取，但 provider
实例还会继续为新 session 工作。

### 13.3 上下文压缩

`agent/conversation_compression.py` 在压缩前调用：

```text
manager.on_pre_compress(messages)
```

provider 可以从即将被压缩或丢弃的消息中抽取事实，或者向压缩摘要提示贡献内容。

压缩成功并创建新 session_id 后，Hermes 会调用：

```text
manager.on_session_switch(new_session_id, parent_session_id=old_session_id, reset=False, reason="compression")
```

这让 provider 更新内部 session 绑定，同时知道逻辑对话仍在继续。

## 14. provider 插件发现与安装

`plugins/memory/__init__.py` 负责发现和加载 provider。

### 14.1 扫描位置

扫描顺序：

1. 仓库内置：`plugins/memory/<name>/`
2. 用户安装：`$HERMES_HOME/plugins/<name>/`

内置 provider 名称优先。如果用户插件与内置插件重名，内置版本胜出。

用户插件需要看起来像 memory provider：`__init__.py` 中包含 `register_memory_provider`
或 `MemoryProvider`。

### 14.2 加载方式

`load_memory_provider(name)` 解析 provider 目录后调用 `_load_provider_from_dir()`。
模块可以用两种方式暴露 provider：

1. plugin-style：定义 `register(ctx)`，并调用 `ctx.register_memory_provider(provider)`。
2. class-style：定义 `MemoryProvider` 子类，由加载器实例化。

用户安装 provider 被加载到 `_hermes_user_memory.<name>` 命名空间，避免和内置
`plugins.memory.<name>` 冲突，也支持相对导入。

### 14.3 CLI 注册

memory provider 的 CLI 命令只为当前 active provider 注册。

`discover_plugin_cli_commands()` 会读取 `memory.provider`，只加载对应 provider 的
`cli.py`。这样禁用 provider 不会污染 `hermes --help`。

## 15. 管理入口

### 15.1 `hermes memory setup`

`hermes_cli/memory_setup.py` 提供交互式 provider 配置：

1. 调用 `discover_memory_providers()`。
2. 用 curses 选择 provider 或 Built-in only。
3. 根据 `plugin.yaml` 安装缺失 pip 依赖。
4. 若 provider 实现 `post_setup(hermes_home, config)`，交给 provider 自己配置。
5. 否则走通用 schema-based setup。
6. 将 `memory.provider` 写入 `config.yaml`。
7. secret 字段写入 `.env`。

### 15.2 Dashboard API

`hermes_cli/web_server.py` 暴露三个相关 API：

| API | 功能 |
|---|---|
| `GET /api/memory` | 返回 active provider、可用 provider 列表、内置 memory 文件大小 |
| `PUT /api/memory/provider` | 设置 `memory.provider`，`builtin` / `none` 会转为空字符串 |
| `POST /api/memory/reset` | 删除 `MEMORY.md`、`USER.md` 或两者 |

Dashboard 的 reset 是文件级删除。删除后下次会话启动时内置 store 会读到空记忆。

## 16. 与 DeerFlow 记忆实现的关键差异

Hermes 和 DeerFlow 都区分“长期记忆”和“会话状态”，但实现思路不同。

| 维度 | DeerFlow | Hermes Agent |
|---|---|---|
| 内置记忆写入 | 会话后 middleware 筛选消息，后台队列调用 LLM 抽取并合并 | 模型主动调用 `memory` 工具写入 curated entries，并由 nudge 周期提醒 |
| 默认存储 | 每用户或 Agent 的 JSON 逻辑结构 | `$HERMES_HOME/memories/MEMORY.md` 与 `USER.md` |
| 注入方式 | 新会话首轮动态注入格式化 memory | 会话系统提示词中注入冻结快照；外部 provider 召回按轮次临时注入用户消息副本 |
| 事实结构 | summary、facts、confidence、来源 thread 等结构化字段 | 内置记忆是短文本 entry；外部 provider 可自行结构化 |
| 更新策略 | LLM 输出结构化 diff，合并、去重、裁剪 | 内置工具 add/replace/remove；外部 provider 自行实现 sync/extract |
| 并发策略 | 防抖队列按 key 合并更新 | 内置文件锁 + 原子替换 + 漂移检测；外部 provider 自己管理队列 |
| 安全重点 | 过滤工具消息、上传文件，避免临时文件写入长期记忆 | 写入和注入双重 threat scan、fenced recall context、stream scrubber、防漂移 |
| 扩展方式 | 自定义 storage class | `MemoryProvider` 插件，最多一个外部 provider 激活 |

可以把 Hermes 的内置 memory 理解为“模型可编辑的长期提示词附录”，把外部 provider
理解为“可插拔的长期召回和会话抽取系统”。

## 17. 实现约束和设计取舍

### 17.1 为什么内置 memory 是字符预算而不是 token 预算

`MemoryStore` 使用字符数限制，因为字符数与模型无关，不需要 tokenizer，也不会因为
切换 provider/model 导致预算解释变化。默认注释按约 2.75 chars/token 粗略估算：

- `MEMORY.md` 2200 chars 约 800 tokens。
- `USER.md` 1375 chars 约 500 tokens。

### 17.2 为什么中途写入不刷新系统提示词

中途刷新会破坏 prefix cache。Hermes 的系统提示词在一个会话内尽量稳定；memory
写入虽然立即持久化，但当前会话的模型已经通过工具结果知道写入成功，不需要马上把
同一条内容重新塞进系统提示词。

### 17.3 为什么外部召回注入到用户消息副本

外部召回常常与当前 query 强相关，应按轮次变化；如果放进系统提示词，会导致提示词
频繁变化并污染 session DB。注入到 API-call-time 的用户消息副本可以做到：

- 当前轮可见；
- 不改变持久会话历史；
- 不影响真实用户消息；
- 不让下一轮无条件继承过期召回。

### 17.4 为什么只允许一个外部 provider

多个 provider 同时启用会带来工具 schema、召回文本、写入镜像和会话结束抽取的多重
冲突。Hermes 保留内置文件记忆作为稳定核心，再允许一个外部 provider 提供增强。

### 17.5 为什么内置写入需要漂移检测

`MEMORY.md` 和 `USER.md` 是普通文本文件，用户、patch 工具、shell 或另一个 session
都可能修改它们。如果工具在不知道这些修改的情况下重写文件，就可能默默丢失外部新增
内容。漂移检测会宁愿拒绝写入并备份，也不冒险覆盖。

## 18. 当前内置 provider 列表

仓库内置 memory provider 位于 `plugins/memory/`：

| Provider | 大致定位 |
|---|---|
| `honcho` | Honcho 后端集成，支持会话、文件上传、检索和写入镜像 |
| `mem0` | Mem0 后端集成 |
| `supermemory` | Supermemory API 集成，提供 save/search/forget/profile 工具 |
| `hindsight` | Hindsight 后端集成，会话结束抽取和文档状态管理 |
| `holographic` | 本地 SQLite / holographic retrieval store |
| `openviking` | OpenViking 后端集成 |
| `retaindb` | RetainDB 后端集成 |
| `byterover` | Byterover 集成，支持预取和压缩前贡献 |

具体 provider 的存储格式、工具名、后台队列和配置字段由各自 `plugins/memory/<name>/`
目录实现。统一契约只保证它们能被 `MemoryManager` 初始化、调用和关闭。

## 19. 测试覆盖入口

与 memory 相关的测试主要集中在：

| 测试文件 | 覆盖点 |
|---|---|
| `tests/tools/test_memory_tool.py` | 内置 `MemoryStore` 增删改、持久化、快照、安全扫描、漂移检测 |
| `tests/agent/test_memory_provider.py` | `MemoryProvider` 默认行为、`MemoryManager` 注册、预取、同步、工具路由、钩子兼容 |
| `tests/agent/test_memory_user_id.py` | gateway 用户身份传递到 provider |
| `tests/agent/test_memory_session_switch.py` | session_id 切换时 provider 状态更新 |
| `tests/run_agent/test_memory_provider_init.py` | provider 初始化路径 |
| `tests/run_agent/test_memory_sync_interrupted.py` | 中断轮次不写入外部 provider |
| `tests/run_agent/test_memory_nudge_counter_hydration.py` | gateway 新 agent 恢复 nudge 计数 |
| `tests/hermes_cli/test_memory_reset.py` | Dashboard / CLI 重置内置 memory 文件 |
| `tests/plugins/memory/*` | 各外部 provider 的行为 |

## 20. 读代码时的推荐顺序

如果要继续深入实现，建议按下面顺序阅读：

1. `tools/memory_tool.py`
2. `agent/agent_init.py` 中 memory 初始化段
3. `agent/system_prompt.py` 中 volatile tier 构建
4. `agent/conversation_loop.py` 中 nudge、prefetch 和 API-call-time 注入
5. `agent/tool_executor.py` 中内置 memory 和外部 provider 工具路由
6. `agent/memory_provider.py`
7. `agent/memory_manager.py`
8. `plugins/memory/__init__.py`
9. 某个具体 provider，例如 `plugins/memory/holographic/__init__.py`

这条路径正好对应“内置文件记忆如何出现、如何写入、如何注入”，再到“外部 provider
如何被发现、如何参与每轮对话、如何在会话边界落盘或抽取”。
