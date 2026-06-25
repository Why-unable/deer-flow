# DeerFlow 记忆模块实现说明

本文基于当前代码实现说明 DeerFlow 长期记忆模块的职责、数据流、存储结构、
隔离策略和配置方式。

## 1. 记忆与会话状态的区别

DeerFlow 中存在两类容易混淆的持久化信息：

| 类型 | 用途 | 主要存储 |
|---|---|---|
| LangGraph checkpoint / thread state | 恢复同一会话中的消息和 Agent 执行状态 | `database` 或旧版 `checkpointer` 配置 |
| 长期记忆（memory） | 从多个会话中提取用户画像、背景、偏好、纠错和长期事实，并影响后续会话 | 每个用户或 Agent 的 `memory.json` |

长期记忆不是完整聊天记录。它只保留经过 LLM 提炼的摘要和事实，目标是让 Agent
在未来独立会话中复用有价值的信息。

## 2. 核心模块

| 模块 | 职责 |
|---|---|
| `agents/middlewares/memory_middleware.py` | 一轮 Agent 执行结束后筛选消息、识别纠错/正向反馈信号并加入更新队列 |
| `agents/memory/message_processing.py` | 仅保留用户消息和最终 AI 回复；过滤工具调用、纯上传提示；识别中英文纠错与肯定表达 |
| `agents/memory/queue.py` | 按 `(thread_id, user_id, agent_name)` 防抖去重，并在后台线程中处理更新 |
| `agents/memory/updater.py` | 调用 LLM 生成结构化更新，校验、合并、去重、裁剪并保存 |
| `agents/memory/prompt.py` | 定义更新提示词，以及将记忆格式化为提示上下文的规则 |
| `agents/memory/storage.py` | 定义存储接口和默认 JSON 文件实现，负责缓存与原子写入 |
| `agents/middlewares/dynamic_context_middleware.py` | 在新会话首条用户消息中注入记忆和当前日期 |
| `agents/lead_agent/prompt.py` | 读取当前用户/Agent 记忆，生成 `<memory>` 注入内容 |
| `config/memory_config.py` | 定义开关、模型、阈值、容量、存储和注入预算 |
| `config/paths.py` | 解析默认运行目录及按用户/Agent 隔离的文件路径 |
| `runtime/user_context.py` | 从当前请求/运行上下文解析有效 `user_id` |
| `app/gateway/routers/memory.py` | 提供查询、重载、清空、导入以及事实增删改 API |

## 3. 完整数据流

下面的目录树覆盖当前长期记忆实现中参与运行的全部核心构件，以及记忆读取、
注入、学习、保存、缓存刷新、失败处理和管理接口的可达分支。目录树不展开通用
Agent、模型提供商和操作系统内部实现。需要注意，长期记忆和 LangGraph
checkpoint 是两套独立机制。

```text
DeerFlow 长期记忆系统
├── 配置与运行上下文
│   ├── MemoryConfig
│   │   ├── enabled
│   │   │   ├── 控制是否学习和保存记忆
│   │   │   └── 与 injection_enabled 一起控制是否注入记忆
│   │   ├── injection_enabled
│   │   │   └── 只控制是否注入，不阻止后台学习
│   │   ├── debounce_seconds
│   │   │   └── 控制防抖队列等待时间
│   │   ├── model_name
│   │   │   └── 选择记忆更新 LLM
│   │   ├── fact_confidence_threshold
│   │   │   └── 决定新事实是否可保存
│   │   ├── max_facts
│   │   │   └── 决定长期存储最多保留多少条事实
│   │   ├── max_injection_tokens
│   │   │   └── 决定一次注入可使用的 token 预算
│   │   ├── storage_class
│   │   │   └── 选择 MemoryStorage 实现
│   │   └── storage_path
│   │       └── 影响 FileMemoryStorage 的全局文件目标
│   ├── 运行时用户上下文
│   │   ├── Agent 请求中解析有效 user_id
│   │   ├── MemoryMiddleware 入队前显式捕获 user_id
│   │   └── Gateway Memory API 按当前有效 user_id 操作
│   ├── Paths / DEER_FLOW_HOME
│   │   └── 决定默认按用户、按 Agent 隔离的文件路径
│   └── MEMORY_UPDATE_PROMPT
│       └── 定义 LLM 应输出的摘要更新、newFacts 与 factsToRemove
│
├── 一次 Agent 请求：读取与注入链路
│   ├── 用户消息进入 DynamicContextMiddleware.before_agent
│   ├── 判断当前会话是否已经包含日期提醒
│   │   ├── 否：新会话首轮
│   │   │   ├── memory.enabled=true 且 injection_enabled=true
│   │   │   │   ├── 请求 storage.load
│   │   │   │   ├── 获得当前用户或指定 Agent 的逻辑记忆
│   │   │   │   ├── format_memory_for_injection
│   │   │   │   │   ├── 先加入 user 与 history 摘要
│   │   │   │   │   ├── facts 按 confidence 从高到低排序
│   │   │   │   │   └── 达到 max_injection_tokens 后停止加入 facts
│   │   │   │   └── 构建隐藏 system-reminder
│   │   │   │       ├── memory
│   │   │   │       └── current_date
│   │   │   └── 任一注入开关为 false
│   │   │       └── 只构建 current_date 提醒
│   │   ├── 是，且日期未变化
│   │   │   └── 不重复注入
│   │   └── 是，但会话已跨日
│   │       └── 只在当前轮注入新日期提醒
│   ├── Lead Agent、工具与子 Agent 执行
│   ├── 向用户返回本轮结果
│   └── 进入 MemoryMiddleware.after_agent 学习链路
│
├── MemoryMiddleware：消息筛选与信号识别
│   ├── 检查 memory.enabled 和 thread_id
│   │   ├── 未启用或无 thread_id
│   │   │   └── 跳过记忆更新
│   │   └── 条件满足
│   │       └── 开始筛选消息
│   ├── 消息筛选
│   │   ├── 保留用户消息
│   │   ├── 保留无 tool_calls 的最终 AI 回复
│   │   ├── 丢弃工具调用过程消息
│   │   └── 处理 uploaded_files 块
│   │       ├── 不包含 uploaded_files
│   │       │   └── 保留原用户消息
│   │       ├── 删除 uploaded_files 后仍有正文
│   │       │   └── 只保留正文，不删除物理文件或原始消息
│   │       └── 删除 uploaded_files 后正文为空
│   │           └── 忽略纯上传消息及紧随的最终 AI 回复
│   ├── 检查筛选后是否同时存在用户消息和 AI 回复
│   │   ├── 否
│   │   │   └── 跳过记忆更新
│   │   └── 是
│   │       └── 继续信号识别
│   ├── 正则识别最近用户消息
│   │   ├── correction_detected
│   │   └── reinforcement_detected
│   └── 显式捕获 user_id，并携带 thread_id 与 agent_name 入队
│
├── MemoryUpdateQueue：防抖队列
│   ├── 队列键
│   │   └── thread_id + user_id + agent_name
│   ├── 防抖窗口内没有同键任务
│   │   ├── 保存 ConversationContext
│   │   └── 启动 daemon threading.Timer
│   ├── 防抖窗口内已有同键任务
│   │   ├── 用最新完整消息列表替换旧消息列表
│   │   ├── correction/reinforcement 标记执行逻辑 OR
│   │   ├── 取消旧 Timer
│   │   └── 重新等待 debounce_seconds
│   ├── Timer 到期
│   │   └── 后台线程调用 MemoryUpdater
│   ├── flush / flush_nowait
│   │   └── 立即处理队列
│   ├── clear
│   │   └── 丢弃所有待处理任务
│   └── 进程提前退出
│       └── daemon 线程中的未完成任务可能丢失
│
├── MemoryUpdater：LLM 更新链路
│   ├── 读取当前逻辑记忆
│   ├── 构建更新提示词
│   │   ├── 当前记忆
│   │   ├── 筛选后的对话
│   │   └── 可选信号提示
│   │       ├── correction_detected=true
│   │       │   └── 提醒 LLM 重点识别错误与正确做法
│   │       └── reinforcement_detected=true
│   │           └── 提醒 LLM 重点识别被肯定的偏好或行为
│   ├── 调用记忆更新 LLM
│   │   ├── 后台队列
│   │   │   └── 在 Timer 后台线程中同步 model.invoke
│   │   ├── aupdate_memory
│   │   │   └── asyncio.to_thread 后执行同步 model.invoke
│   │   └── 运行中事件循环调用同步 update_memory
│   │       ├── 提交到专用同步线程池
│   │       └── 同步调用方等待 future.result
│   ├── LLM 调用或解析失败
│   │   └── 本次更新失败，不部分写入
│   └── LLM 输出可安全解析
│       ├── 应用 user/history 中 shouldUpdate=true 的摘要
│       ├── 按 factsToRemove 删除指定旧事实
│       ├── 逐条处理 newFacts
│       │   ├── confidence 低于 fact_confidence_threshold
│       │   │   └── 不保存该新事实
│       │   ├── 规范化文本与已有事实完全相同
│       │   │   └── 跳过新事实，不提升旧事实 confidence
│       │   └── 达到阈值且文本不重复
│       │       └── 添加事实并记录来源 thread
│       ├── facts 超过 max_facts
│       │   └── 按 confidence 降序保留前 max_facts 条
│       ├── 再次清理上传文件相关描述
│       └── 调用 storage.save
│
├── MemoryStorage：存储与缓存链路
│   ├── get_memory_storage 首次初始化
│   │   ├── storage_class 可加载且是 MemoryStorage 子类
│   │   │   └── 创建自定义 MemoryStorage
│   │   ├── storage_class 无法加载或类型不合法
│   │   │   └── 回退到 FileMemoryStorage
│   │   └── 将实例缓存为进程内存储单例
│   ├── storage.load
│   │   ├── 自定义 MemoryStorage
│   │   │   └── 由自定义 load 返回逻辑记忆结构
│   │   └── FileMemoryStorage
│   │       ├── 获取当前文件 mtime
│   │       ├── 当前 mtime 与缓存 mtime 相同
│   │       │   └── 返回缓存数据
│   │       └── mtime 不同或没有缓存
│   │           ├── 文件不存在、JSON 错误或 IO 错误
│   │           │   └── 使用空记忆结构
│   │           ├── 文件读取成功
│   │           │   └── normalize 补齐标准字段
│   │           └── 更新读取缓存与 mtime
│   ├── storage.reload
│   │   ├── FileMemoryStorage
│   │   │   └── 强制重新读取文件并更新缓存
│   │   └── 自定义 MemoryStorage
│   │       └── 由自定义 reload 决定刷新方式
│   └── storage.save
│       ├── 自定义 MemoryStorage
│       │   └── 由自定义 save 决定持久化方式
│       └── FileMemoryStorage
│           ├── 选择文件目标
│           │   ├── 默认按 user_id / agent_name 隔离
│           │   └── 绝对 storage_path 可让全局记忆文件共享
│           ├── 写入随机命名临时文件
│           ├── replace 原子替换目标文件
│           │   ├── 失败：返回 false，保留原目标文件
│           │   └── 成功：更新缓存和 mtime
│           └── 最终形成 memory.json
│
└── Gateway Memory API：人工管理链路
    ├── 获取数据 / 导出 / status
    │   └── storage.load 后返回当前用户记忆
    ├── 获取 config
    │   └── 返回当前 MemoryConfig
    ├── 导入 / 清空 / facts 增删改
    │   ├── 按当前有效 user_id 修改逻辑记忆
    │   └── 调用 storage.save
    └── reload
        └── 调用 storage.reload 强制刷新
```

### 3.1 会话日期提醒

“会话日期提醒”不是长期记忆本身，而是
`DynamicContextMiddleware.before_agent()` 在模型看到用户消息前插入的一条隐藏
`HumanMessage`。它的内容使用 `<system-reminder>` 包裹，至少包含当前日期：

```text
<system-reminder>
<current_date>2026-06-23, Tuesday</current_date>
</system-reminder>
```

当 `memory.enabled: true` 且 `memory.injection_enabled: true` 时，这条提醒还会
同时包含 `<memory>...</memory>`；如果记忆注入关闭，则只包含日期。它的作用有
两个：

- 告诉模型“当前日期”，让“今天、昨天、上周、最近”等相对时间表达有明确基准；
- 把记忆注入从静态系统提示词中移出来，使基础 system prompt 在不同用户和会话
  间保持稳定，便于前缀缓存复用。

提醒是“会话级”的：新会话第一轮会在第一条真实用户消息前插入完整提醒，并通过
`additional_kwargs.dynamic_context_reminder=true` 标记为隐藏动态上下文消息。
后续同一天的轮次不会重复注入。若同一会话跨过午夜，系统会在当前轮前再插入一条
轻量日期更新提醒，只更新 `<current_date>`，不重新注入完整记忆：

```text
第一天首轮：
  hidden reminder = memory + current_date
  real user message = 用户原始问题

同一天后续轮次：
  不新增 reminder

跨日后的下一轮：
  hidden reminder = 新 current_date
  real user message = 用户原始问题
```

这条隐藏提醒会进入 LangGraph 的消息状态，因此会被同一会话后续轮次看到；但它
不是 `memory.json` 的一部分，也不会被当作用户事实保存。摘要压缩中间件会识别
并保留这种隐藏提醒，避免压缩后系统误以为还没有注入过日期。

### 3.2 消息筛选

`MemoryMiddleware.after_agent()` 在 Agent 完成后运行。它只在
`memory.enabled: true` 且能够取得 `thread_id` 时工作。

真实执行顺序是先取得并校验 `thread_id`，再读取和筛选消息、识别信号，最后在
加入后台队列前显式捕获 `user_id`。信号识别放在 `user_id` 捕获之前没有特殊业务
含义；关键约束只是必须在离开当前请求上下文、进入 Timer 后台线程之前保存
`user_id`。

进入更新队列前，系统会：

- 保留用户消息；
- 保留没有 `tool_calls` 的最终 AI 回复；
- 丢弃工具调用过程消息；
- 从用户消息中移除 `<uploaded_files>` 块；
- 如果一轮内容只有上传提示，则同时忽略对应 AI 回复；
- 使用正则表达式检测用户是否明确纠正 Agent，或明确肯定某种做法。

这样可避免把工具执行细节和仅在当前会话有效的上传文件写入长期记忆。

移除 `<uploaded_files>` 块只会修改“送给记忆更新器的消息副本”，不会删除物理
文件、原始会话消息或上传记录。例如：

```text
原始用户消息：
<uploaded_files>
- /mnt/user-data/uploads/report.pdf
</uploaded_files>
请分析报告中的风险。

记忆更新器看到的用户消息：
请分析报告中的风险。
```

如果删除上传块后消息为空，说明用户本轮只有上传行为，没有可长期学习的用户
表达。系统会忽略这条纯上传消息，并忽略紧随其后的最终 AI 回复，避免产生
“用户上传了 report.pdf”或“Agent 已收到文件”之类未来无法复用的记忆。

纠错和正向反馈的第一步识别不调用 LLM。系统使用预定义中英文正则表达式检查
最近六条消息中的用户消息，例如：

- 纠错：`不对`、`你理解错了`、`重新来`、`改用`；
- 正向反馈：`完全正确`、`正是我想要的`、`继续保持`。

匹配结果只是一个提示信号。后续仍由记忆更新 LLM 理解“具体纠正了什么”或
“具体肯定了什么”。因此，这里的“正向强化”不是强化学习，也不会直接提升已有
事实的置信度；更准确的名称是“正向反馈提示”。

### 3.3 防抖队列

队列使用 `(thread_id, user_id, agent_name)` 作为更新目标的唯一键。在
`debounce_seconds` 时间内，同一目标的新内容会替换旧内容，并合并已检测到的
纠错/正向反馈标记。

“防抖”表示每次收到同一目标的新更新时，都取消旧计时器并重新开始等待。默认
等待 30 秒时，用户在 30 秒内连续补充三次要求，通常只触发一次记忆 LLM 调用。
这可以减少调用费用和文件写入，也让记忆 LLM 看到更完整的最新会话。

队列用最新完整消息列表替换旧列表，但纠错和正向反馈标记使用逻辑 OR 合并。
例如，第一次入队检测到纠错，第二次入队没有检测到纠错，最终
`correction_detected` 仍为 `true`。它不会直接改写记忆，而是确保后续 LLM
仍收到“这批会话中曾出现纠错，请重点分析”的提示。

因此，如果会话前 `n` 条筛选后消息已经在较早一次更新中被学习过，后续新状态又
传入完整的 `n+m` 条筛选后消息，队列不会自动只截取新增的 `m` 条。实际执行是：

1. `MemoryMiddleware.after_agent()` 从当前 `ThreadState.messages` 生成一份新的
   筛选后完整消息列表；
2. `MemoryUpdateQueue` 用这份最新完整列表替换同键旧列表；
3. Timer 到期后，`MemoryUpdater` 将“当前 `memory.json`”和“这份完整筛选后
   对话文本”一起交给记忆更新 LLM；
4. LLM 根据已有记忆和完整对话输出增量建议；
5. `_apply_updates()` 再按 `shouldUpdate`、`factsToRemove`、`newFacts`、
   `confidence` 和内容去重规则落盘。

换句话说，`n+m` 条会一起进入 LLM 提示词，去重和避免重复保存主要依赖两层机制：
一是提示词中同时给出当前 `memory.json`，让 LLM 不必重复输出已存在事实；二是
`_apply_updates()` 会对新事实按规范化后的 `content` 去重。如果同一事实只是换
了一种说法，代码层面不会做语义去重，仍依赖 LLM 判断是否重复。

例子：

```text
第一次已学习：
  messages = [U1, A1, U2, A2]
  memory.json 已保存 fact_1 = "用户偏好 SQLite 本地调试。"

下一轮后当前状态：
  messages = [U1, A1, U2, A2, U3, A3]

Timer 到期后实际交给记忆 LLM：
  current_memory = 包含 fact_1 的 memory.json
  conversation = U1/A1/U2/A2/U3/A3 的筛选后文本

合理输出：
  不重复输出 "用户偏好 SQLite 本地调试。"
  只输出 U3/A3 中新出现的长期事实，或输出 factsToRemove 修正旧事实
```

队列通过 daemon `threading.Timer` 在后台处理。由于 Python `ContextVar`
不会自动传播到新线程，`MemoryMiddleware` 必须在入队时显式捕获 `user_id`，
否则后台更新可能写入错误用户。

可以把请求线程理解为正在处理 Alice 请求的工作人员。该执行上下文知道
`current_user_id = alice`。记忆更新会延迟执行，因此 Timer 创建另一个后台
工作人员；新线程不会自动继承前一个线程的 `ContextVar`，重新查询用户时可能只
得到无认证模式的 `default`。所以系统必须在入队时把 `"alice"` 写入
`ConversationContext.user_id`，后台线程之后直接使用这个明确值：

```text
请求执行上下文：知道当前用户是 alice
    └─ 入队时保存 user_id=alice
        └─ 后台线程读取保存值
            └─ 写入 users/alice/memory.json
```

该队列是进程内、尽力而为的机制。进程在后台任务完成前退出时，尚未处理的更新
可能丢失。

### 3.4 LLM 提取与合并

`MemoryUpdater` 使用 `memory.model_name` 指定的模型；未指定时使用默认模型，
并强制关闭 thinking。更新调用使用同步 `model.invoke()` 路径，异步调用场景会
转移到线程执行，避免阻塞事件循环或复用错误的异步 HTTP 连接池。

同步 `model.invoke()` 会等待网络响应，适合在线程中执行，但不应直接占住负责
并发请求的事件循环。可以把事件循环理解为接待请求的调度员，把同步 LLM 调用
转移到工作线程后，调度员可以在等待 LLM 时继续处理其他请求：

```text
直接在事件循环中同步等待：
Alice 请求 ──等待记忆 LLM 10 秒──> 完成
Bob 请求   ──被阻塞──────────────> 稍后处理

转移到工作线程：
Alice 请求 ──> 工作线程等待记忆 LLM
事件循环   ──> 同时继续处理 Bob 请求
```

当前实现特意复用同步 LLM 调用路径，以避免 LangChain/httpx 的异步连接池被不同
事件循环错误复用。`aupdate_memory()` 使用 `asyncio.to_thread()`，可以在等待时
把控制权交还事件循环；同步 `update_memory()` 在检测到运行中的事件循环时会提交
到专用同步线程池，但随后等待 `future.result()`，因此同步调用方自身仍会等待。
防抖队列本来就在 Timer 后台线程中运行，不会占用原请求的事件循环。

这里的“同步/异步”可以分成三种实际入口：

```text
入口 A：防抖队列的后台 Timer 线程
  MemoryUpdateQueue._process_queue
  -> MemoryUpdater.update_memory
  -> 当前线程不是 asyncio 事件循环
  -> 直接执行 _do_update_memory_sync
  -> model.invoke 阻塞的是 Timer 后台线程
  -> 原始用户请求已经结束，不被这次等待占用

入口 B：同步函数在已有事件循环中调用 update_memory
  async LangGraph / FastAPI 调用栈中误调用 update_memory
  -> update_memory 检测到 loop.is_running()
  -> 提交到 _SYNC_MEMORY_UPDATER_EXECUTOR
  -> 工作线程执行 _do_update_memory_sync + model.invoke
  -> 调用方等待 future.result()
  -> 好处是同步 HTTP 连接池不碰 async httpx 连接池
  -> 代价是这个同步调用方仍然要等结果返回

入口 C：异步代码显式调用 aupdate_memory
  await MemoryUpdater().aupdate_memory(...)
  -> asyncio.to_thread(_do_update_memory_sync)
  -> 工作线程执行 model.invoke
  -> 当前事件循环可在 await 期间调度其他任务
  -> 返回后再继续解析、合并、保存结果
```

具体来说，DeerFlow 的常规学习链路走入口 A：Agent 完成后只把筛选消息放入
`MemoryUpdateQueue`，真正 LLM 更新在稍后的 Timer 后台线程中执行。因此用户本轮
响应不会等待记忆 LLM。入口 B 和入口 C 主要用于测试、管理脚本或未来其他模块
直接调用 `MemoryUpdater` 的场景。

LLM 必须输出以下结构：

```json
{
  "user": {
    "workContext": {"summary": "...", "shouldUpdate": true},
    "personalContext": {"summary": "...", "shouldUpdate": false},
    "topOfMind": {"summary": "...", "shouldUpdate": true}
  },
  "history": {
    "recentMonths": {"summary": "...", "shouldUpdate": true},
    "earlierContext": {"summary": "...", "shouldUpdate": false},
    "longTermBackground": {"summary": "...", "shouldUpdate": false}
  },
  "newFacts": [],
  "factsToRemove": []
}
```

该结构不是最终 `memory.json`，而是对当前记忆的“增量修改建议”：

- `user.workContext`：当前职业角色、主要项目和技术栈；
- `user.personalContext`：语言、沟通偏好、个人兴趣；
- `user.topOfMind`：当前仍在推进或重点关注的事项；
- `history.recentMonths`：最近 1–3 个月的活动摘要；
- `history.earlierContext`：大约 3–12 个月前仍有价值的背景；
- `history.longTermBackground`：长期稳定的专业背景和工作方式；
- `newFacts`：建议新增的离散事实；
- `factsToRemove`：已被新信息否定、需要删除的旧事实 ID。

只有 `shouldUpdate: true` 的摘要建议会替换 `memory.json` 中对应摘要。LLM 输出中
的 `shouldUpdate` 不会保存进文件；最终文件改为记录 `updatedAt`。

合并阶段执行以下规则：

- 只有 `shouldUpdate: true` 且摘要非空的上下文段会被替换；
- `factsToRemove` 按事实 ID 删除旧事实；
- 新事实只有达到 `fact_confidence_threshold` 才会保存；
- 事实内容会去除首尾空白，并以规范化后的内容去重；
- 超过 `max_facts` 时，按置信度降序保留；
- 对明确纠错可记录 `category: correction` 和可选 `sourceError`；
- 保存前再次清理所有上传文件相关描述；
- LLM 返回结构不完整或不安全时，本次更新失败，不部分写入。

#### 事实与置信度

`confidence` 是一条事实记录的属性，表示系统对该事实陈述可靠程度的判断。所谓
“将正确做法保存为高置信度”，完整含义是：把正确做法描述成一条 `fact`，并给
这条事实设置较高 `confidence`，而不是给抽象的“做法”对象设置属性。

自动学习时，`confidence` 由记忆更新 LLM 在 `newFacts` 中给出；通过管理 API
手动创建或修改事实时，由 API 调用方给出。DeerFlow 代码负责校验、过滤、排序和
使用该值，但目前不会自行计算事实真实性，也不会根据重复出现次数自动调整它。

```json
{
  "content": "DeerFlow 本地开发应使用 make dev 启动。",
  "category": "correction",
  "confidence": 0.98,
  "sourceError": "此前错误地建议使用 npm start。"
}
```

`confidence` 当前有三个作用：

1. 新事实只有达到 `fact_confidence_threshold` 才写入长期记忆存储；
2. 事实超过 `max_facts` 时，优先保留高置信度事实；
3. 注入 token 预算不足时，优先注入高置信度事实。

纠错或正向反馈标记只会向 LLM 增加提示。例如 `correction_detected = true`
会要求 LLM 重点识别正确做法，并在适当时输出 `category: correction`、
`confidence >= 0.95` 的新事实。代码不会因为该标记直接新增事实。

当前实现也不会因为用户再次肯定同一事实，就提高已有事实的 `confidence`。如果
LLM 再次输出文本完全相同的事实，简单文本去重会跳过新事实，旧事实置信度保持
不变。

#### 当前“事实合并”的边界

当前实现执行的是“应用更新与精确文本去重”，不是完整的语义事实合并：

- 可以按 `factsToRemove` 删除指定旧事实；
- 可以添加达到阈值且文本不重复的新事实；
- 去除首尾空白后文本完全相同的新事实会被跳过；
- 不会把含义相近但文本不同的事实自动合成一条；
- 不会自动提高旧事实置信度；
- 不会保存一条事实被多次肯定的计数。

例如“用户偏好 FastAPI”和“用户主要使用 FastAPI 开发后端”目前可能同时存在。
完整的语义事实合并通常还需要 embedding 相似度或额外 LLM 判断、冲突处理、
来源合并和置信度更新策略。

### 3.4 原子存储与缓存

默认 `FileMemoryStorage` 使用 JSON 文件。保存时先写入随机命名的临时文件，再用
`replace()` 替换目标文件，避免进程中途失败留下半写文件。

内存缓存键为 `(user_id, agent_name)`，并记录文件修改时间。文件修改时间变化后，
下一次 `load()` 会自动重新读取；`reload()` 可强制刷新缓存。

具体过程是：缓存保存 `(memory_data, file_mtime)`；每次 `load()` 先通过
`file_path.stat().st_mtime` 获取当前修改时间。如果当前值与缓存值一致，直接返回
缓存；如果不同，则重新读取文件、规范化结构并更新缓存。这是每次加载时主动
检查，不是操作系统主动通知。

如果自定义 `storage_class` 无法加载或不是 `MemoryStorage` 子类，系统记录错误并
回退到 `FileMemoryStorage`。

自定义 `storage_class` 用于替换“在哪里、如何持久化记忆”，例如 Redis、
PostgreSQL、S3 或加密文件，而不是用于随意改变 DeerFlow 使用的逻辑数据结构。
自定义类必须继承 `MemoryStorage` 并实现：

```python
class RedisMemoryStorage(MemoryStorage):
    def load(self, agent_name=None, *, user_id=None) -> dict:
        ...

    def reload(self, agent_name=None, *, user_id=None) -> dict:
        ...

    def save(self, memory_data, agent_name=None, *, user_id=None) -> bool:
        ...
```

存储后端内部可以使用不同物理格式，但 `load()` 返回的数据仍应包含 DeerFlow
更新器和注入器依赖的 `user`、`history` 和 `facts` 等字段。

## 4. 数据结构

默认 JSON 结构如下：

```json
{
  "version": "1.0",
  "lastUpdated": "2026-06-14T00:00:00Z",
  "user": {
    "workContext": {"summary": "", "updatedAt": ""},
    "personalContext": {"summary": "", "updatedAt": ""},
    "topOfMind": {"summary": "", "updatedAt": ""}
  },
  "history": {
    "recentMonths": {"summary": "", "updatedAt": ""},
    "earlierContext": {"summary": "", "updatedAt": ""},
    "longTermBackground": {"summary": "", "updatedAt": ""}
  },
  "facts": [
    {
      "id": "fact_12345678",
      "content": "用户偏好简洁的技术说明。",
      "category": "preference",
      "confidence": 0.95,
      "createdAt": "2026-06-14T00:00:00Z",
      "source": "thread-id",
      "sourceError": null
    }
  ]
}
```

事实类别包括 `preference`、`knowledge`、`context`、`behavior`、`goal` 和
`correction`。

这种结构将整体背景摘要和可独立管理的事实结合起来：

- `user` 回答“这个用户现在是谁、当前关注什么”；
- `history` 用压缩摘要表达背景如何随时间演变；
- `facts` 保存可排序、删除、审阅和追踪来源的离散陈述；
- `confidence` 支持保存过滤、容量淘汰和注入排序；
- `source`、`createdAt`、`updatedAt` 支持审查与追踪；
- `sourceError` 让纠错事实同时说明正确方法和应避免的旧方法；
- `version` 为未来数据迁移预留版本。

摘要适合表达整体语境，但不方便精确删除；事实适合精确管理，但仅靠事实列表难以
表达完整背景。因此使用“摘要 + 离散事实”的混合结构。

## 5. 用户与 Agent 隔离

默认运行数据根目录由 `DEER_FLOW_HOME` 决定；未设置时通常为项目根目录下的
`.deer-flow/`。

| 范围 | 默认路径 |
|---|---|
| 用户全局记忆 | `{base_dir}/users/{user_id}/memory.json` |
| 用户的指定 Agent 记忆 | `{base_dir}/users/{user_id}/agents/{agent_name}/memory.json` |
| 无 `user_id` 的旧版全局记忆 | `{base_dir}/memory.json` |
| 无 `user_id` 的旧版 Agent 记忆 | `{base_dir}/agents/{agent_name}/memory.json` |

无认证模式下，有效用户 ID 默认为 `default`。用户 ID 和 Agent 名称均会校验，
防止路径穿越。

`storage_path` 的行为需要特别注意：

- 为空时，使用上表中的按用户隔离路径；
- 相对路径只影响无 `user_id` 的旧版全局路径；正常按用户路径仍按用户隔离；
- 绝对路径会让所有用户共享同一个文件，相当于主动退出用户隔离；
- 指定 Agent 的记忆始终使用 Agent 专属路径，不使用全局 `storage_path`。

## 6. 记忆注入

在新会话首轮，`DynamicContextMiddleware` 将格式化后的记忆放入：

```xml
<system-reminder>
<memory>
...
</memory>
<current_date>...</current_date>
</system-reminder>
```

该提醒被写入首条用户消息并在会话内保持不变，以利于模型前缀缓存。因此，后台
新增的记忆通常在下一个新会话中生效，而不会不断改写当前会话的首条消息。

格式化规则：

- 先注入用户上下文和历史摘要；
- 事实按置信度从高到低排序；
- 在 `max_injection_tokens` 预算内尽量加入事实；
- `correction` 事实可附带 `avoid: ...`，提醒 Agent 避免重复错误；
- 使用 `tiktoken` 计数；不可用时按字符数估算。

默认 `max_injection_tokens` 为 2000，但这不意味着 `memory.json` 中的所有事实
都会注入。系统先放入 `user` 和 `history` 摘要，再按 `confidence` 从高到低加入
尽可能多的事实，达到预算后停止。

`tiktoken` 是 token 计数库，`cl100k_base` 是其中一种文本切分编码规则。DeerFlow
使用它估算记忆文本的 token 数；不同模型可能使用不同 tokenizer，因此对非对应
模型这是近似预算。若 `tiktoken` 不可用，则退化为 `字符数 / 4` 的粗略估算。

2000 token 相对模型上下文窗口的大致占比：

| 模型上下文窗口 | 2000 token 占比 |
|---:|---:|
| 32K | 约 6.25% |
| 64K | 约 3.13% |
| 128K | 约 1.56% |
| 200K | 约 1% |

外层 `<memory>`、`<system-reminder>` 和日期还会额外占用少量 token。记忆实际以
隐藏的提醒用户消息进入模型上下文，并非标准 `SystemMessage`，但同样占用上下文
窗口。

`memory.enabled: false` 会停止更新和注入；`memory.injection_enabled: false`
只停止注入，仍允许后台学习和保存。

## 7. 运行示例

下面 13 个示例均按实际执行顺序说明参与模块和数据变化。大多数“学习并保存”
场景复用以下基础链路，具体示例会标出在哪一步发生分支：

```text
LangGraph ThreadState.messages
  -> MemoryMiddleware.after_agent
  -> message_processing.filter_messages_for_memory
  -> detect_correction / detect_reinforcement
  -> MemoryUpdateQueue.add
  -> ConversationContext(thread_id, user_id, agent_name, messages, signals)
  -> threading.Timer 到期
  -> MemoryUpdater.update_memory
  -> FileMemoryStorage.load 当前 memory.json
  -> format_conversation_for_update + MEMORY_UPDATE_PROMPT
  -> 记忆更新 LLM 返回 JSON
  -> MemoryUpdater._apply_updates
  -> FileMemoryStorage.save 原子写入 memory.json
```

新会话读取和注入则使用另一条链路：

```text
DynamicContextMiddleware.before_agent
  -> FileMemoryStorage.load
  -> format_memory_for_injection
  -> 隐藏 HumanMessage(<system-reminder><memory>...</memory>)
  -> Lead Agent
```

### 7.1 普通偏好被保存并在新会话注入

用户在 `thread-a` 中明确说：

```text
我主要使用 FastAPI 开发 Python 后端，代码示例请带类型注解。
```

本轮完成后，记忆更新 LLM 可能输出：

```json
{
  "user": {
    "workContext": {
      "summary": "用户主要使用 FastAPI 开发 Python 后端。",
      "shouldUpdate": true
    }
  },
  "newFacts": [
    {
      "content": "用户偏好带类型注解的 Python 代码示例。",
      "category": "preference",
      "confidence": 0.95
    }
  ]
}
```

代码将摘要和事实合并进 Alice 的 `memory.json`。Alice 新建 `thread-b` 后询问
“帮我写一个认证接口”，首轮隐藏提醒会包含该偏好，Agent 可以直接生成 FastAPI
风格且带类型注解的代码。

本例的数据流分为“学习”和“新会话注入”两段：

```text
学习阶段
  ThreadState.messages
    [HumanMessage("我主要使用 FastAPI..."), AIMessage(...)]
  -> MemoryMiddleware.after_agent
  -> filter_messages_for_memory 保留用户消息和最终 AI 回复
  -> MemoryUpdateQueue 保存 thread-a + alice + messages
  -> MemoryUpdater 将当前 memory.json 与对话文本发给记忆更新 LLM
  -> LLM JSON 中的 workContext.summary 和 newFacts
  -> _apply_updates 增加时间、fact_id、source=thread-a
  -> FileMemoryStorage.save 写入 users/alice/memory.json

注入阶段
  thread-b 首条 HumanMessage("帮我写一个认证接口")
  -> DynamicContextMiddleware.before_agent
  -> FileMemoryStorage.load 读取 Alice 的 memory.json
  -> format_memory_for_injection 转为文本记忆
  -> 在原用户消息前插入隐藏 reminder
  -> Lead Agent 同时看到记忆偏好与真实问题
```

### 7.2 纯上传不会形成长期记忆

用户消息只有：

```xml
<uploaded_files>
- /mnt/user-data/uploads/report.pdf
</uploaded_files>
```

删除上传块后用户消息为空，因此该消息及紧随的最终 AI 回复不进入记忆更新。
文件仍保留在当前 thread 的 uploads 目录，只是不会生成长期事实。

参与模块和数据变化如下：

```text
UploadsMiddleware
  -> 将物理上传文件路径包装进 <uploaded_files> 块
  -> ThreadState.messages 包含纯上传 HumanMessage 和对应 AIMessage
  -> MemoryMiddleware.after_agent
  -> filter_messages_for_memory 删除 <uploaded_files> 块
  -> 用户正文变成空字符串
  -> 丢弃该 HumanMessage，并用 skip_next_ai 丢弃紧随的 AIMessage
  -> 筛选结果不同时包含 human 和 ai
  -> 不调用 MemoryUpdateQueue，不读取或写入 memory.json
```

`uploads/report.pdf` 属于 thread 文件系统数据，过滤过程只复制和修改内存中的消息，
不会删除该物理文件，也不会修改 checkpoint 中的原始消息。

### 7.3 上传文件同时带有真实要求

```xml
<uploaded_files>
- /mnt/user-data/uploads/report.pdf
</uploaded_files>
这份报告属于 Apollo 项目。以后讨论 Apollo 时优先关注成本风险。
```

记忆筛选后只保留正文。LLM 可能保存“Apollo 项目优先关注成本风险”，但不会保存
`report.pdf` 的临时路径。

本例在消息筛选阶段与 7.2 分叉：

```text
原始 HumanMessage
  "<uploaded_files>...report.pdf...</uploaded_files>\n这份报告属于 Apollo 项目..."
-> filter_messages_for_memory
-> 删除上传块后仍有正文
-> 浅复制 HumanMessage，并把 content 改为
   "这份报告属于 Apollo 项目。以后讨论 Apollo 时优先关注成本风险。"
-> MemoryUpdateQueue
-> MemoryUpdater
-> 记忆更新 LLM 只接收到清理后的正文
-> _strip_upload_mentions_from_memory 再次清理意外出现的上传路径
-> FileMemoryStorage.save
```

### 7.4 用户纠正 Agent

```text
Agent：建议使用 npm start 启动 DeerFlow。
用户：不对，本地开发应该使用 make dev。
```

正则检测到“不对”，设置 `correction_detected = true`。记忆 LLM 收到额外纠错
提示后，可能输出：

```json
{
  "content": "DeerFlow 本地开发应使用 make dev 启动。",
  "category": "correction",
  "confidence": 0.98,
  "sourceError": "此前错误地建议使用 npm start。"
}
```

未来注入时，该事实可能显示为：

```text
- [correction | 0.98] DeerFlow 本地开发应使用 make dev 启动。
  (avoid: 此前错误地建议使用 npm start。)
```

参与模块和信号变化如下：

```text
过滤后的最近消息
  [AIMessage("建议使用 npm start..."), HumanMessage("不对，...make dev")]
-> detect_correction 匹配“不对”
-> correction_detected=true
-> MemoryUpdateQueue 将该布尔值写入 ConversationContext
-> MemoryUpdater._build_correction_hint
-> 在 MEMORY_UPDATE_PROMPT 中增加纠错提示
-> 记忆更新 LLM 输出 category=correction、confidence>=0.95、sourceError
-> _apply_updates 保存正确做法和应避免的旧做法
-> format_memory_for_injection 在未来会话中渲染 `(avoid: ...)`
```

### 7.5 用户肯定某种做法

```text
Agent：先给结论，再列出关键证据。
用户：对，就是这样，继续保持。
```

正则检测到正向反馈，并提示记忆 LLM 考虑保存高置信度 `preference` 或
`behavior` 事实，例如“用户偏好先给结论再列证据”。如果已有完全相同事实，当前
代码会跳过重复项，不会提高旧事实的置信度。

参与模块和数据变化如下：

```text
过滤后的最近消息
-> detect_correction=false
-> detect_reinforcement 匹配“对，就是这样”或“继续保持”
-> reinforcement_detected=true
-> ConversationContext
-> MemoryUpdater._build_correction_hint 增加正向强化提示
-> 记忆更新 LLM 可能输出高置信度 preference / behavior
-> _apply_updates 使用规范化 content 生成去重键
   -> 不存在：创建新 fact
   -> 已存在：跳过，不修改旧 fact 的 confidence
-> FileMemoryStorage.save
```

### 7.6 防抖合并连续对话

默认防抖为 30 秒：

```text
10:00:00 用户：帮我分析部署问题。
10:00:10 用户：补充，只分析 Docker 部署。
10:00:20 用户：还需要关注公网入口。
10:00:50 队列执行一次记忆更新。
```

每次新内容都会重置 Timer，同一 `(thread_id, user_id, agent_name)` 最终只保留
最新完整消息列表。如果第一轮检测到纠错、后续轮没有，纠错标记仍通过逻辑 OR
保留。

队列内部的数据变化如下：

```text
10:00:00 MemoryMiddleware -> queue.add(context-v1)
  _queue = [ConversationContext(messages=v1)]
  Timer = 30 秒

10:00:10 queue.add(context-v2)
  根据 (thread_id, user_id, agent_name) 找到 v1
  用最新完整 messages=v2 替换 v1
  correction/reinforcement 使用逻辑 OR 合并
  取消旧 Timer，重新计时 30 秒

10:00:20 queue.add(context-v3)
  同样替换为 v3 并重置 Timer

10:00:50 Timer -> MemoryUpdateQueue._process_queue
  清空共享队列并获得 contexts_to_process=[v3]
  -> MemoryUpdater 只执行一次更新
```

### 7.7 Alice 与 Bob 的后台更新保持隔离

```text
Alice 请求线程：入队 user_id=alice
Bob 请求线程：入队 user_id=bob
后台 Timer 线程：分别读取已保存的 user_id
```

即使后台线程本身没有请求级 `ContextVar`，也会分别写入：

```text
.deer-flow/users/alice/memory.json
.deer-flow/users/bob/memory.json
```

隔离依赖的数据流如下：

```text
Alice 的 Agent runtime
  -> MemoryMiddleware 调用 resolve_runtime_user_id(runtime)
  -> queue.add(user_id="alice")
  -> ConversationContext 显式保存 alice

Bob 的 Agent runtime
  -> queue.add(user_id="bob")
  -> ConversationContext 显式保存 bob

Timer 后台线程
  -> 不依赖请求 ContextVar
  -> MemoryUpdater(..., user_id=context.user_id)
  -> FileMemoryStorage._get_memory_file_path
  -> 分别解析为 users/alice/memory.json 和 users/bob/memory.json
```

因此用户隔离信息在跨越 `threading.Timer` 前已经固化进队列项，不会因后台线程
缺少请求上下文而退化成共享文件。

### 7.8 外部编辑文件后自动刷新缓存

第一次 `load()` 读取 Alice 的文件并缓存其 `mtime=100`。管理员在磁盘上修改文件，
系统看到新的 `mtime=200`。下一次 `load()` 比较发现不一致，重新读取文件并更新
缓存。调用 `/api/memory/reload` 则会直接强制重新读取。

参与模块和缓存状态变化如下：

```text
首次 FileMemoryStorage.load(user_id="alice")
  -> stat(memory.json).st_mtime = 100
  -> _load_memory_from_file 解析 JSON
  -> _memory_cache[(alice, None)] = (memory_data, 100)

管理员修改文件
  -> 磁盘 JSON 改变，mtime = 200
  -> 内存缓存仍是旧数据和 mtime=100

下一次 load()
  -> 当前 mtime=200 != cached mtime=100
  -> 重新解析文件
  -> _memory_cache[(alice, None)] = (new_memory_data, 200)

/api/memory/reload
  -> 直接调用 storage.reload
  -> 不使用命中的旧缓存，强制读取并覆盖缓存
```

### 7.9 注入预算不足时只选择高优先级事实

假设 `memory.json` 有 100 条事实，共约 6000 token，而
`max_injection_tokens=2000`：

1. 先放入 `user` 和 `history` 摘要；
2. 将事实按 `confidence` 从高到低排序；
3. 逐条加入，直到接近 2000 token；
4. 低置信度且排在后面的事实仍保存在文件中，但本次不注入。

模块顺序和数据变化如下：

```text
DynamicContextMiddleware.before_agent
-> FileMemoryStorage.load 得到完整 memory_data（仍含全部 100 条事实）
-> format_memory_for_injection(max_tokens=2000)
   1. 格式化 user 和 history，并统计已用 token
   2. 按 confidence 降序生成 ranked_facts
   3. 使用 tiktoken 逐条计算 fact line 成本
   4. 下一条会超预算时停止
-> 生成小于等于预算的 <memory> 文本
-> 隐藏 reminder 注入 ThreadState.messages
-> Lead Agent 只看到本次被选中的高优先级事实
```

该过程只改变本次模型输入，不修改 `memory.json`，也不会删除未注入的事实。

### 7.10 低置信度事实不会写入长期存储

如果 LLM 只是弱推测：

```json
{
  "content": "用户可能偏好 Kubernetes。",
  "category": "preference",
  "confidence": 0.55
}
```

默认 `fact_confidence_threshold=0.7`，因此该新事实不会写入 `memory.json`。
摘要字段是否更新由各字段的 `shouldUpdate` 单独决定，不受事实阈值控制。

本例的关键分支发生在 `MemoryUpdater._apply_updates`：

```text
记忆更新 LLM JSON
  newFacts=[{content: "用户可能偏好 Kubernetes。", confidence: 0.55}]
-> _parse_memory_update_response 校验并规范化结构
-> _apply_updates
   -> user/history 中 shouldUpdate=true 的摘要仍可更新
   -> 遍历 newFacts
   -> 0.55 < fact_confidence_threshold(0.7)
   -> 跳过该 fact，不生成 fact_id
-> FileMemoryStorage.save 保存其他合法变化
```

### 7.11 新信息否定旧事实

已有事实：

```json
{
  "id": "fact_old",
  "content": "用户偏好 PostgreSQL。",
  "confidence": 0.9
}
```

用户后来明确表示“这个项目改用 MySQL，不再使用 PostgreSQL”。记忆 LLM 可以在
同一次完整更新中输出以下相关部分：

```json
{
  "newFacts": [
    {
      "content": "当前项目使用 MySQL。",
      "category": "context",
      "confidence": 0.98
    }
  ],
  "factsToRemove": ["fact_old"]
}
```

合并阶段先删除 `fact_old`，再添加新事实。是否识别矛盾以及应删除哪个 ID 依赖
记忆 LLM 对当前完整记忆和新对话的判断。

参与模块和事实集合变化如下：

```text
FileMemoryStorage.load
  -> current_memory.facts 包含 fact_old
-> MemoryUpdater._prepare_update_prompt
  -> 将 current_memory 和“改用 MySQL”对话同时交给记忆更新 LLM
-> LLM 返回 factsToRemove=["fact_old"] + MySQL newFact
-> _parse_memory_update_response 校验删除 ID 和新事实结构
-> _apply_updates
   1. 从 facts 中删除 id=fact_old
   2. confidence=0.98 通过阈值
   3. 创建新的 fact_id、createdAt、source
-> FileMemoryStorage.save 原子替换 memory.json
```

### 7.12 更新失败与配置开关

- LLM 调用异常、输出无法解析或结构不安全：本次更新失败，不部分写入；
- 文件原子写入失败：保留原目标文件并返回失败；
- `memory.enabled: false`：不学习，也不注入已有记忆；
- `memory.enabled: true` 且 `injection_enabled: false`：继续后台学习和保存，但
  后续会话不注入记忆；
- 自定义 `storage_class` 无法加载或类型不合法：记录错误并回退到
  `FileMemoryStorage`。

这些分支分别在不同模块提前终止或降级：

```text
memory.enabled=false
  -> DynamicContextMiddleware 不注入记忆
  -> MemoryMiddleware.after_agent / MemoryUpdateQueue.add 直接返回

injection_enabled=false
  -> DynamicContextMiddleware 只注入日期，不读取并注入长期记忆
  -> MemoryMiddleware、Queue、Updater 和 Storage 学习链路仍继续

记忆更新 LLM 异常或 JSON 非法
  -> MemoryUpdater 捕获异常并返回 false
  -> 不进入 _apply_updates / save，原 memory.json 保持不变

更新 JSON 存在不安全的部分结构
  -> _parse_memory_update_response 拒绝该响应
  -> 不执行部分事实删除或部分写入

FileMemoryStorage.save 写入失败
  -> 临时文件无法原子 replace
  -> 返回 false，原目标文件和原缓存对象不被部分更新

storage_class 无法导入或不是 MemoryStorage 子类
  -> get_memory_storage 捕获异常
  -> 创建 FileMemoryStorage 作为当前进程的存储单例
```

### 7.13 全局记忆与指定 Agent 记忆隔离

Alice 使用默认 Lead Agent 时，记忆读写目标通常是：

```text
.deer-flow/users/alice/memory.json
```

Alice 使用名为 `research-analyst` 的指定 Agent 时，`agent_name` 会成为队列键和
存储范围的一部分，目标变为：

```text
.deer-flow/users/alice/agents/research-analyst/memory.json
```

因此同一个用户的通用偏好与某个专用 Agent 学到的上下文可以分别维护；Bob 的
对应文件仍位于 `users/bob/` 下。

路径选择由 `agent_name` 在整个链路中持续传递：

```text
默认 Lead Agent
  MemoryMiddleware(agent_name=None)
  -> queue key=(thread_id, alice, None)
  -> MemoryUpdater(agent_name=None, user_id=alice)
  -> FileMemoryStorage._get_memory_file_path
  -> users/alice/memory.json

research-analyst
  MemoryMiddleware(agent_name="research-analyst")
  -> queue key=(thread_id, alice, "research-analyst")
  -> MemoryUpdater(agent_name="research-analyst", user_id=alice)
  -> FileMemoryStorage._get_memory_file_path
  -> users/alice/agents/research-analyst/memory.json
```

读取注入时也使用相同的 `user_id + agent_name` 组合，因此写入隔离和后续读取隔离
保持一致。

### 7.14 记忆更新的同步与异步执行路径

#### 7.14.1 常规用户对话：后台 Timer 线程更新

这是线上最常见的路径。用户本轮请求完成后，记忆学习只是入队，不会让用户等待
记忆 LLM：

```text
10:00:00 Alice 发起请求
  -> DynamicContextMiddleware.before_agent 注入日期和可用记忆
  -> Lead Agent 生成回复
  -> MemoryMiddleware.after_agent 筛选消息并 queue.add(...)
  -> 本轮响应返回给 Alice

10:00:30 Timer 到期
  -> MemoryUpdateQueue._process_queue 在线程 Timer-1 中运行
  -> MemoryUpdater.update_memory(...)
  -> 当前不是 asyncio 事件循环
  -> _do_update_memory_sync(...)
  -> model.invoke(...) 同步等待记忆 LLM
  -> _finalize_update 解析、合并、FileMemoryStorage.save
```

这个场景中，“同步”指 `model.invoke()` 是阻塞调用；但它阻塞的是后台 Timer
线程，不是已经返回响应的用户请求线程，也不是 FastAPI/LangGraph 的事件循环。

#### 7.14.2 事件循环中误用同步入口：转移到专用线程池

如果某个异步函数里直接调用 `update_memory()`，当前线程通常已经有正在运行的
事件循环。实现会把真正的同步 LLM 调用转移到专用线程池：

```python
async def some_async_handler(messages):
    ok = MemoryUpdater().update_memory(messages, thread_id="thread-a")
    return ok
```

实际执行：

```text
some_async_handler 所在线程存在 running event loop
-> update_memory 检测到 loop.is_running()
-> _SYNC_MEMORY_UPDATER_EXECUTOR.submit(_do_update_memory_sync, ...)
-> memory-updater-sync 工作线程执行 model.invoke
-> some_async_handler 等待 future.result()
-> 返回 true / false
```

这样做的重点不是让调用方完全不等待，而是避免在事件循环线程里直接跑阻塞 I/O，
同时避免复用 LangChain provider 的异步 HTTP 连接池。同步调用方仍然会等结果；
如果希望事件循环在等待期间继续调度其他任务，应使用 `aupdate_memory()`。

#### 7.14.3 显式异步入口：`aupdate_memory()`

异步代码可以显式 `await`：

```python
async def some_async_handler(messages):
    ok = await MemoryUpdater().aupdate_memory(messages, thread_id="thread-a")
    return ok
```

实际执行：

```text
some_async_handler
-> await aupdate_memory(...)
-> asyncio.to_thread(_do_update_memory_sync, ...)
-> 工作线程执行同步 model.invoke
-> event loop 在 await 期间可以继续处理其他协程
-> 工作线程返回后，当前协程恢复并拿到 true / false
```

这个路径适合异步测试、管理接口或未来直接在异步模块中触发记忆更新的场景。当前
常规 Agent 学习路径已经由防抖队列放到后台 Timer 线程中，不需要再额外调用
`aupdate_memory()`。

#### 7.14.4 为什么不直接使用异步 LLM 调用

当前实现刻意让记忆更新统一走同步 `model.invoke()`。原因是 DeerFlow 主 Agent
本身运行在异步图执行环境中，部分 LangChain provider 会缓存异步 HTTP client 或
连接池。如果记忆更新在另一个事件循环中使用异步 LLM 调用，可能触发跨事件循环
复用异步连接池的问题。统一使用同步调用并放到普通工作线程，可以把记忆更新的
HTTP 连接池与主 Agent 的异步连接池隔离开。

## 8. 配置参考

```yaml
memory:
  enabled: true
  storage_path: ""
  storage_class: deerflow.agents.memory.storage.FileMemoryStorage
  debounce_seconds: 30
  model_name: null
  max_facts: 100
  fact_confidence_threshold: 0.7
  injection_enabled: true
  max_injection_tokens: 2000
```

| 字段 | 默认值 | 约束与含义 |
|---|---:|---|
| `enabled` | `true` | 总开关，控制记忆更新；注入逻辑也会检查该值 |
| `storage_path` | `""` | 全局记忆文件路径；绝对路径会绕过用户隔离 |
| `storage_class` | `deerflow.agents.memory.storage.FileMemoryStorage` | `MemoryStorage` 实现类的导入路径 |
| `debounce_seconds` | `30` | 更新防抖秒数，范围 `1..300` |
| `model_name` | `null` | 更新记忆使用的模型名，`null` 表示默认模型 |
| `max_facts` | `100` | 最大事实数，范围 `10..500` |
| `fact_confidence_threshold` | `0.7` | 保存事实的最低置信度，范围 `0..1` |
| `injection_enabled` | `true` | 是否把已有记忆注入后续会话 |
| `max_injection_tokens` | `2000` | 注入预算，范围 `100..8000` |

## 9. 管理接口

Gateway 在 `/api/memory` 下提供记忆管理能力：

| 方法与路径 | 用途 |
|---|---|
| `GET /api/memory` | 获取当前用户记忆 |
| `POST /api/memory/reload` | 从存储重新加载 |
| `DELETE /api/memory` | 清空当前用户记忆 |
| `POST /api/memory/facts` | 手动创建事实 |
| `PATCH /api/memory/facts/{fact_id}` | 修改事实 |
| `DELETE /api/memory/facts/{fact_id}` | 删除事实 |
| `GET /api/memory/export` | 导出当前用户完整记忆 |
| `GET /api/memory/config` | 查看生效配置 |
| `GET /api/memory/status` | 查看配置和当前数据 |
| `POST /api/memory/import` | 导入完整记忆数据 |

这些接口通过运行时有效 `user_id` 操作当前用户的全局记忆，不直接管理某个
自定义 Agent 的专属记忆。

## 10. 实现边界与注意事项

- 长期记忆是 LLM 提取结果，可能存在遗漏或误判，应通过 API/UI 允许用户审阅和修正。
- 防抖队列位于单进程内，尚不是跨进程可靠消息队列。
- `memory.json` 包含用户画像和长期背景，应作为敏感运行数据保护，不应提交到 Git。
- 修改 `storage_class` 后，已创建的全局存储单例不会自动迁移已有数据。
- `database`、`checkpointer` 和 `run_events` 不负责保存长期记忆 JSON。
- 当前没有语义事实合并、已有事实置信度强化、事实肯定次数统计或时间衰减机制。
