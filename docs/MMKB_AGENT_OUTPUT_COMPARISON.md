# DeerFlow 前端与 MMKB Agent Mode 输出能力对比

## 文档目的

本文对比以下两条 Agent 输出链路：

1. DeerFlow 自带前端直接消费 DeerFlow Gateway / LangGraph 事件；
2. MMKB 的 OpenAI 兼容 `chat_completion` Agent Mode，将 DeerFlow 事件转换为
   OpenAI Chat Completions SSE。

目标是说明两种展示方式当前分别支持哪些输出、MMKB 做了哪些转换，以及仍然
存在的能力差距。本文仅记录当前实现，不修改接口行为。

## 总体结论

DeerFlow 自带前端理解 DeerFlow 和 LangGraph 的结构化消息、状态与事件，
可以将思考、工具调用、子 Agent、文件和 Token Usage 渲染为独立交互组件。

MMKB Agent Mode 面向 OpenWebUI、Cherry Studio 等通用 OpenAI 客户端，
必须兼容 OpenAI Chat Completions 协议。因此，它将 DeerFlow 的结构化事件
压缩成两个主要文本通道：

```text
content            最终回答、澄清内容、文件下载链接
reasoning_content  思考过程、工具状态、检索状态、子任务状态和错误摘要
```

MMKB 当前已经覆盖主要用户可见信息，但无法直接提供 DeerFlow 自带前端中的
复杂结构化交互。

## 相关实现文件

### DeerFlow 前端

- `frontend/src/core/threads/hooks.ts`
- `frontend/src/core/messages/utils.ts`
- `frontend/src/components/workspace/messages/message-group.tsx`
- `frontend/src/components/workspace/messages/message-list.tsx`
- `frontend/src/components/workspace/messages/message-list-item.tsx`
- `frontend/src/components/workspace/messages/subtask-card.tsx`
- `frontend/src/components/workspace/artifacts/`

### MMKB Agent Mode

- `mmkb/app/services/deerflow_agent_adapter.py`
- `mmkb/app/services/chat_completion.py`
- `mmkb/app/services/deerflow_artifacts.py`
- `mmkb/app/services/deerflow_threads.py`

## DeerFlow 自带前端显示的内容

### 最终回答

最终回答作为独立 Assistant 消息显示，并支持：

- Markdown；
- 链接；
- 图片；
- 引用；
- 流式文本；
- 复制回答。

### 模型思考过程

前端能够识别 AI Message 中的 `reasoning_content`、thinking content 或行内
thinking 标签，并显示为独立的可折叠思考区域。

用户可以：

- 查看当前是否仍在思考；
- 展开或折叠思考内容；
- 将思考步骤与后续工具调用区分开。

### 结构化工具调用

DeerFlow 前端将工具调用渲染为独立步骤，并能够关联工具参数和 ToolMessage
结果。

| 工具类型 | 自带前端展示方式 |
|---|---|
| `web_search` | 搜索关键词和可点击结果 |
| `image_search` | 图片缩略图和来源链接 |
| `web_fetch` | 可点击网页标题 |
| `read_file` | 读取的文件路径 |
| `write_file` / `str_replace` | 文件路径，可打开文件预览 |
| `bash` | 命令代码块 |
| `ask_clarification` | 独立澄清交互 |
| `write_todos` | 计划和任务状态 |
| 其他工具 | 工具名称、描述和执行状态 |

### 子 Agent

DeerFlow 自带前端为每个子 Agent 显示独立任务卡片，内容包括：

- 子任务描述；
- 子任务 Prompt；
- 当前执行状态；
- 正在使用的工具；
- 子 Agent 完整结果；
- 失败信息；
- 展开与折叠状态。

自带前端使用：

```typescript
streamSubgraphs: true
```

因此能够实时接收和展示子 Agent 的内部执行过程。

### 文件与 Artifacts

DeerFlow 自带前端不只显示 Markdown 下载链接，还提供：

- 当前 thread 的 Artifact 文件列表；
- Artifacts 侧边栏；
- 文件内容预览；
- 文件下载；
- 新生成文件自动打开；
- 文件写入过程的预览。

### Token Usage

前端可以展示不同粒度的 Token Usage：

- 单个消息；
- 单个思考或工具步骤；
- 子 Agent；
- 整个 Assistant turn；
- 整个 thread；
- reasoning token 和操作归因。

### 其他状态

自带前端还能够显示或维护：

- thread 标题；
- thread 历史记录；
- 上传文件；
- 澄清请求；
- Todo 计划；
- LLM 重试提示；
- 错误 Toast；
- summarization 后的消息历史；
- 可恢复的 thread 状态。

## MMKB Agent Mode 当前输出

MMKB Agent Mode 将 DeerFlow 事件转换为 OpenAI Chat Completions SSE：

```json
{
  "choices": [
    {
      "delta": {
        "content": "...",
        "reasoning_content": "..."
      }
    }
  ]
}
```

是否显示 `reasoning_content`，取决于 OpenWebUI、Cherry Studio 或其他客户端
是否支持该扩展字段。

### `content` 通道

当前会输出：

- Agent 最终回答；
- Agent 澄清问题；
- 已生成文件的签名下载链接；
- Agent 正文中 `/mnt/user-data/outputs/*` 链接的改写结果；
- 用于恢复多轮 DeerFlow thread 的隐藏 marker。

文件输出示例：

```text
[文件] 已生成：[report.md](http://mmkb.example/api/agent/artifacts/...)
```

### `reasoning_content` 通道

MMKB 将 DeerFlow 工具调用和运行事件格式化为面向用户的中文摘要。

示例：

```text
[检索] 正在搜索本地知识库：NIST CSF（hybrid）
[检索结果] “NIST CSF” 找到 7 个文本片段、2 个图片/视觉证据。
[文档] 正在读取文档预览：...
[子任务] 开始：分析风险管理
[子任务] 完成：分析风险管理
[文件] 正在准备展示生成文件
[工具错误] grep: Permission denied
[token-usage] input=..., output=..., total=...
```

当前包含以下过程信息：

- RAG 检索请求与结果数量；
- 文档信息、预览、片段、图片和集合读取；
- 网页和图片搜索状态；
- 文件读取、写入、目录查看和修改；
- Bash 命令；
- Todo 计划与状态；
- 子任务开始、完成和异常；
- 文件准备状态；
- 工具错误；
- Token Usage 汇总。

### MMKB 的额外适配处理

MMKB Agent Mode 不只是简单转发 DeerFlow 输出，还执行以下适配：

- 将 DeerFlow 结构化事件转换为 OpenAI 兼容 SSE；
- 把过程信息映射到 `reasoning_content`；
- 去重重复工具调用、工具结果、Token Usage 和 Artifact；
- 屏蔽 Title、Summarization 等内部消息流；
- 关闭子 Agent 子图流，防止子 Agent 正文混入最终回答；
- 将常见工具状态翻译为中文摘要；
- 将 DeerFlow 内部 Artifact 路径改写为 MMKB 签名下载链接；
- 第二轮对话时抑制上一轮已出现的 Artifact；
- 在不同输出类型之间插入换行；
- 使用隐藏 thread marker 恢复多轮 DeerFlow thread；
- 对 raw `/mnt/user-data/outputs/*` 链接进行流式安全重写。

## 能力对比

| 能力 | DeerFlow 自带前端 | MMKB Agent Mode |
|---|---|---|
| 最终回答 | 结构化 Markdown Assistant 消息 | `content` 文本 |
| 模型思考 | 独立可折叠区域 | `reasoning_content`，取决于客户端支持 |
| 工具调用 | 独立结构化步骤 | 中文文本摘要 |
| 工具参数 | 可按工具定制展示 | 只显示部分必要参数 |
| 工具结果 | 可关联并展示详细结果 | 只摘要部分已知工具结果 |
| 子 Agent | 实时任务卡片、结果和错误 | 开始、完成和异常文本摘要 |
| 子 Agent 实时过程 | 支持 | 已关闭 |
| 文件 | 文件列表、预览、下载面板 | Markdown 签名下载链接 |
| 图片搜索 | 缩略图和来源 | 搜索状态摘要 |
| 网页搜索结果 | 可点击结果列表 | 搜索状态摘要 |
| 澄清 | 专用交互组件 | 普通文本 |
| Todo | 结构化计划步骤 | 文本计划摘要 |
| Token Usage | 按步骤、消息、turn 和 thread 展示 | 一段总量汇总文本 |
| Thread | 原生持久化、标题和历史 | 隐藏 marker 恢复关联 |
| 错误 | Toast 和结构化失败状态 | `[deerflow-error]` / `[工具错误]` 文本 |
| Artifact 状态 | 保存在 thread state 并可浏览 | 转为签名下载链接 |

## 当前主要差距

### 结构化信息被压缩为文本

MMKB Agent Mode 输出工具和任务状态，但客户端无法把这些状态恢复为 DeerFlow
前端那样的专用 UI 组件。

### 子 Agent 可观察性较低

当前关闭了子 Agent 子图流，以避免内部消息和子 Agent 正文混入最终回答。
因此 MMKB 只能显示子任务开始、完成和异常，不能展示实时工具过程和完整结果
卡片。

### 文件只有下载链接

MMKB 已确保用户可以下载生成文件，但通用 OpenAI 客户端通常没有 Artifact
侧边栏、文件内容预览和写入过程预览。

### 工具结果展示有限

MMKB 对常用 RAG 工具结果进行了摘要，但不会把所有 ToolMessage 原始结果都
发送给客户端。这样可以减少噪音和泄漏内部数据，但也减少了可观察性。

### 客户端兼容性不一致

`reasoning_content` 不是所有 OpenAI Chat Completions 客户端都统一支持的
标准字段。不同客户端可能：

- 正常显示为思考过程；
- 将其忽略；
- 将其混入正文；
- 对 Markdown 或流式换行处理不同。

## 当前取舍是否合理

对于面向通用 OpenAI 客户端的接口，当前取舍总体合理：

- 保留最终回答和主要过程状态；
- 不暴露复杂内部结构；
- 不让子 Agent 正文污染主回答；
- 保证生成文件可下载；
- 保持 OpenAI Chat Completions 兼容性。

MMKB 当前实现已经接近通用 OpenAI Chat Completions 协议能够稳定表达的能力
上限。继续增加纯文本状态可以提升信息量，但无法复制 DeerFlow 自带前端的
完整交互体验。

## 后续扩展方向

### 继续保持通用 OpenAI 兼容

可以在不改变协议的前提下继续优化：

- 补充更多常用工具的中文状态摘要；
- 进一步减少重复或无意义过程信息；
- 改善不同客户端中的 Markdown 和换行兼容；
- 为工具错误增加更清晰的用户提示；
- 允许按请求控制过程信息详细程度。

### 定义 MMKB 专用结构化事件协议

如果希望接近 DeerFlow 自带前端体验，可以额外定义专用 SSE 事件，例如：

```text
event: agent_tool_started
event: agent_tool_completed
event: agent_subtask_updated
event: agent_artifact_created
event: agent_reasoning_delta
```

这需要接入前端专门支持该协议，不能只依赖现有 OpenAI Chat Completions
客户端。

### 建立 MMKB 专用 Agent 前端

若未来需要完整呈现：

- 子 Agent 卡片；
- Artifact 预览；
- 结构化工具过程；
- 详细 Token Usage；
- Thread 管理；

则应考虑建立 MMKB 专用 Agent 前端，或复用 DeerFlow 前端的消息和 Artifact
组件，而不是继续扩展纯文本 OpenAI 接口。

## 建议验证场景

后续调整输出转换逻辑时，建议验证：

| 场景 | 期望结果 |
|---|---|
| 简单问候 | 只显示简洁最终回答，不出现无关工具状态 |
| 本地知识检索 | 显示检索请求、结果数量和最终回答 |
| 多工具研究 | 不重复显示相同工具调用和结果 |
| 子 Agent 任务 | 显示开始、完成或异常，但不混入子 Agent 正文 |
| 文件生成 | 只出现一次可用的签名下载链接 |
| 第二轮普通回复 | 不重复显示上一轮 Artifact |
| 工具错误 | 在 reasoning 中显示清晰错误，不破坏最终回答 |
| 不支持 reasoning 的客户端 | 最终回答仍然完整可用 |

