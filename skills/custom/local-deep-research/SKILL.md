---
name: local-deep-research
description: 当用户需要基于本地知识库回答一个具体问题、解释一个主题、分析某个概念/系统/文档集，或生成基于本地证据的普通研究回答时使用此 skill。优先使用 rag_search、rag_get_document、rag_get_document_preview、rag_get_document_chunks 和 rag_get_document_assets。若用户明确要求系统性文献综述、survey、annotated bibliography、多篇论文/报告的跨文档方法比较、纳入/排除筛选或证据矩阵，应改用 local-systematic-literature-review。
---

# 本地深度研究 Skill

## 概览

当本地文档应作为主要事实来源时，此 skill 提供一套系统化方法，用于开展基于本地知识库的充分研究。**在开始普通本地深度研究回答或内容生成任务前，先加载此 skill**。

如果用户明确要求系统性文献综述、survey、annotated bibliography、多篇论文/报告的跨文档方法比较、纳入/排除筛选或证据矩阵，应使用 `local-systematic-literature-review`，而不是此 skill。

它借鉴了深度网页研究的深度和多角度结构，但调整了证据优先级：

1. 本地知识库优先
2. 定向阅读文档其次
3. 只有在本地证据存在缺口时，才进行有限的网页研究

## 何时使用此 Skill

**以下情况始终加载此 skill：**

### 本地知识研究问题

- 用户询问 "what is X"、"explain X"、"research X"、"investigate X"
- 用户只给出一个宽泛主题，并期望得到有依据的研究回答
- 用户询问某个概念、项目、文档集、内部系统、架构或知识库主题
- 用户明确要求搜索本地知识库
- 回答应基于已上传或已索引的 PDF/文档内容
- 单次检索查询不足以给出合适回答
- 任务重点是回答一个具体问题，而不是构建多文档综述集合

### 基于本地来源的内容生成

- 从知识库创建报告、摘要、简报、PPT 大纲或文档
- 基于内部文档生成比较或建议
- 从已索引 PDF 中提取需求、架构说明、风险或实现细节
- 任何必须可追溯到本地证据的内容

### 不使用此 Skill 的情况

- 用户要求“系统性文献综述”“literature review”“survey”“annotated bibliography”“SLR”。
- 用户要求比较多篇本地论文、报告、标准或白皮书的方法、发现、局限。
- 用户要求建立纳入/排除标准、候选文档矩阵、证据矩阵或跨文档主题综合。
- 用户的目标是形成多文档综述报告，而不是回答一个具体研究问题。

以上情况使用 `local-systematic-literature-review`。

## 核心原则

### 本地路径禁用规则

本地知识库文档内容只能通过 `rag_*` 工具读取。允许使用的读取路径是：`rag_search`、`rag_list_documents`、`rag_get_document`、`rag_get_document_preview`、`rag_get_document_chunks`、`rag_get_document_assets` 和 `rag_list_collections`。

禁止把 MMKB 返回的 `input_file_path`、`markdown_merged_path`、`markdown_image_dir_path`、`md_asset_base`、`image_abs` 或任何 `/home/.../storage/...`、`documents/.../markdown/...` 一类路径交给 `grep`、`read_file`、`bash`、`ls` 等文件/命令工具。那些路径是 MMKB 服务端元数据或 URL 线索，不是 DeerFlow sandbox 内可读文件。需要正文时用 `rag_get_document_preview` 或 `rag_get_document_chunks`；需要图片时用 `rag_get_document_assets` 或 `rag_search` 返回的 `image_url`。

面向用户输出本地文档或图片链接时，只能逐字复制 `rag_*` 工具返回的
`document_url`、`image_url` 等现成 URL。禁止根据 `document_id` 手写、
拼接、重排或猜测 URL；工具未返回 URL 时，只展示标题与证据 ID。

**当用户请求可以从本地知识库回答时，绝不要把通用知识或网页片段当作主要来源。**

输出质量取决于本地检索的广度、文档阅读的深度，以及证据综合的清晰度。单次 `rag_search` 查询绝不足以支撑深度研究。

网页工具只能作为有限补充使用，并且要把来自网页的信息标记为外部背景。

## 研究方法

### 阶段 1：主题框定

如果用户只提供一个主题，先将其拆解为具体研究角度：

1. **定义和范围**：这个主题是什么？包含或排除什么？
2. **架构或组件**：它有哪些部分、工作流或实现模块？
3. **使用场景和示例**：它在哪里使用？提到了哪些具体案例？
4. **比较和替代方案**：它与什么相似或不同？
5. **风险、缺口和限制**：哪些内容不清楚、有争议、不完整或存在风险？

示例：
```text
主题："deepagents-backend"

初始角度：
- 定义和预期用途
- 后端架构和关键模块
- 与 LangChain/LangGraph 的关系
- 暴露的 API 和集成模式
- 限制、部署假设或开放问题
```

### 阶段 2：宽泛本地探索

从宽泛的本地检索开始，理解知识库整体情况：

1. **初始调研**：对主主题使用 `rag_search`。
2. **变体查询**：搜索别名、缩写、英文/中文变体、相关模块名，以及可能的文件/文档标题。
3. **识别文档**：记录候选 `document_id`、标题、文件名、相关片段和匹配角度。
4. **绘制范围图**：识别哪些文档覆盖哪些维度，以及哪些维度仍然薄弱。

默认使用：
```text
rag_search(query="<topic>", mode="hybrid", limit=10)
```

使用多组查询：
```text
"deepagents-backend"
"deepagents backend"
"DeepAgents backend architecture"
"LangGraph deepagents backend"
"deepagents API"
```

### 阶段 3：定向本地深挖

针对每个重要维度，开展定向本地研究：

1. **具体查询**：针对每个子主题使用精确的 `rag_search` 查询。
2. **多种表述**：尝试不同名称、同义词、缩写和实现术语。
3. **文档元数据**：对相关候选文档使用 `rag_get_document`。
4. **阅读完整上下文**：对最重要的文档使用 `rag_get_document_preview`。
5. **跟进本地线索**：如果预览中提到其它模块、文档名、术语或相关系统，也继续搜索这些内容。

示例：
```text
维度："API integration"

定向本地搜索：
- "deepagents backend API"
- "deepagents backend endpoints"
- "deepagents LangGraph thread run stream"
- "deepagents external call"

随后检查：
- rag_get_document(document_id)
- rag_get_document_preview(document_id, max_chars=12000)
```

### 阶段 4：精确证据和视觉资产检查

本地知识库同时索引文本块和视觉资产。不要只看 `chunks`；当检索结果包含 `assets`，或问题涉及图表、截图、架构图、扫描页、图片 OCR、表格截图时，必须检查视觉证据。

#### rag_search 返回值使用规则

`rag_search` 返回的 JSON 包含：

- `chunks`：直接命中的文本块，是主要文字证据来源。
- `assets`：图片/视觉资产，既可能是直接命中的图片，也可能是由命中文本块关联出来的图片。

处理 `assets` 时遵守：

- `hit=true`：该图片资产本身被检索直接命中。适合回答关于图、截图、扫描件、表格图片、视觉内容的问题。
- `hit=false` 且 `from_chunk_ids` 非空：该图片是命中文本块关联出来的上下文图片。它通常适合放在相关文字结论附近辅助解释。
- `image_url`：面向用户的图片 URL。需要展示图片时，使用 Markdown：`![简短说明](image_url)`。
- `caption_or_ocr`：图片 OCR 或说明文本，可作为辅助证据，但要意识到 OCR 可能有误。
- `image_abs`：服务端本地路径。不要暴露给用户，除非明确是在调试系统内部问题。
- `from_chunk_ids` 可以和 `rag_get_document_chunks` 返回的 chunk `id` 对齐，用于确认图片关联的是哪段文本。

#### 何时使用 rag_get_document_chunks

在以下情况使用 `rag_get_document_chunks`：

- 需要验证 `rag_search` 命中文本块的上下文。
- 需要查看相邻或同文档其它 chunk，避免断章取义。
- 需要精确引用 chunk id、页码或原始文本。
- 需要把 `assets.from_chunk_ids` 和具体文本块对齐。
- `rag_get_document_preview` 太长，且你只需要按 chunk 精确阅读。

#### 何时使用 rag_get_document_assets

在以下情况使用 `rag_get_document_assets`：

- 用户问题涉及图片、图表、架构图、截图、扫描页、视觉布局或 OCR 内容。
- `rag_search` 返回了有价值的图片资产，需要查看更多同文档视觉证据。
- 文本证据提到了“如下图”“见图”“截图”“表格”“页面”等视觉线索。
- 需要找到可展示的 `image_url`，或核对 `caption_or_ocr`。

图片使用原则：

- 如果图片能帮助解释结论，可以在相关段落附近插入 Markdown 图片。
- 图片前后留空行，避免和正文挤在一起。
- 图片不替代文字证据；关键判断仍需绑定到文本 chunk、OCR/caption 或文档上下文。
- 对 OCR/caption 支撑的判断使用较弱表达，例如“图片 OCR 显示”“该图似乎包含”。

### 阶段 5：证据多样性和验证

通过寻找多种证据类型来确保本地覆盖充分：

| 证据类型 | 目的 | 本地查询提示 |
|---|---|---|
| **定义** | 明确含义和范围 | "overview", "introduction", "what is", "definition" |
| **架构** | 理解结构和流程 | "architecture", "workflow", "graph", "backend", "module" |
| **API 和接口** | 识别集成点 | "API", "endpoint", "request", "response", "stream" |
| **示例和案例** | 用具体用法支撑判断 | "example", "demo", "use case", "scenario" |
| **配置** | 理解运行参数 | "config", "yaml", "environment", "deployment" |
| **限制和风险** | 避免单方面结论 | "limitation", "risk", "caveat", "todo", "known issue" |
| **比较** | 将主题放入上下文 | "vs", "compare", "alternative", "difference" |
| **视觉证据** | 验证图表、截图、扫描页和 OCR 内容 | "figure", "image", "screenshot", "diagram", "图", "截图", "表格" |

### 阶段 6：候选文档矩阵

在综合前，先构建一份内部候选文档矩阵：

| 字段 | 需要记录的内容 |
|---|---|
| `document_id` | 本地知识库工具返回的 UUID 或标识符 |
| 标题 / 文件名 | 人类可读的来源名称 |
| 匹配角度 | 它支撑哪个研究维度 |
| 证据强度 | 高 / 中 / 低 |
| 关键摘录 | 简短转述证据，不要复制长段落 |
| 视觉证据 | 相关 `image_url`、`asset id`、OCR/caption 或“无” |
| 缺口 | 这个文档没有回答什么 |

优先选择符合以下条件的文档：
- 直接关于该主题
- 已处理且可用
- 在实现或概念细节上内容丰富
- 在多个相关查询中反复出现

### 阶段 7：有限网页补充

只有当本地证据因特定原因不足时，才使用 `web_search` 和 `web_fetch`：

- 本地语料缺少通用背景或公开定义
- 用户询问最新/当前的外部信息
- 需要将本地说法与公开文档或标准进行比较
- 需要补足缺失上下文，才能负责任地解释某份本地文档

使用网页工具前，先在内部说明缺口：
```text
本地证据解释了内部工作流，但没有解释它依赖的公开 LangGraph 概念。使用有限的 web_fetch 获取官方/公开上下文。
```

使用网页工具时：
1. 围绕缺失点进行窄范围搜索。
2. 必要时完整获取权威来源。
3. 将结果标记为外部补充上下文。
4. 除非用户要求外部验证，否则不要让网页结果覆盖本地证据。

### 阶段 8：综合检查

回答前，确认：

- [ ] 我是否已从至少 3-5 个角度搜索本地知识库？
- [ ] 我是否已检查最相关的候选文档？
- [ ] 我是否已对高价值文档使用 `rag_get_document_preview`？
- [ ] 如果问题涉及图表/截图/扫描页/图片 OCR，我是否已检查 `assets` 或使用 `rag_get_document_assets`？
- [ ] 如果需要精确上下文，我是否已使用 `rag_get_document_chunks` 对齐 chunk id、页码或图片关联？
- [ ] 我是否能将关键判断绑定到本地文档证据？
- [ ] 我是否已区分本地证据和外部网页补充？
- [ ] 我是否已识别本地证据缺口或薄弱点？

**如果任何答案是“否”，在生成最终回答前继续进行本地研究。**

## 搜索策略提示

### 有效的本地查询模式

```text
# 从宽泛开始
"[topic]"
"[topic] overview"
"[topic] architecture"

# 搜索实现维度
"[topic] backend"
"[topic] API"
"[topic] config"
"[topic] workflow"
"[topic] deployment"

# 搜索关系
"[topic] LangGraph"
"[topic] LangChain"
"[topic] agent"
"[topic] thread"

# 搜索限制
"[topic] limitation"
"[topic] issue"
"[topic] todo"
"[topic] risk"
```

### 多语言检索

当主题名称可能以多种语言出现时，同时搜索两种语言：

```text
"knowledge base retrieval"
"local RAG"
"local deep research"
"deepagents backend"
"deepagents backend translated terms"   # 当语料中可能存在翻译术语时，也尝试翻译后的说法
```

### 检索模式

- 默认使用 `mode="hybrid"`。
- 当措辞可能与用户查询不同，使用 `mode="semantic"`。
- 搜索精确名称、ID、API 路径、配置键或错误消息时，使用 `mode="sparse"`。

### 何时使用 rag_get_document

在以下情况使用 `rag_get_document`：
- 某个搜索命中识别出有价值的文档
- 需要状态、标题、来源路径、生成的 markdown 路径或元数据
- 需要决定是否读取完整预览

### 何时使用 rag_get_document_preview

在以下情况使用 `rag_get_document_preview`：
- 文档与主题直接相关
- 片段太短，不足以支撑可靠结论
- 需要周边上下文、章节结构，或同一文档中的多个细节
- 最终回答将基于该文档提出强判断

### 何时使用 rag_get_document_chunks

在以下情况使用 `rag_get_document_chunks`：
- 需要精确阅读某个文档的分块内容
- 需要验证检索命中的 chunk 是否被正确理解
- 需要使用 chunk id、页码或原文片段作为证据
- 需要把图片资产的 `from_chunk_ids` 映射回具体文本

### 何时使用 rag_get_document_assets

在以下情况使用 `rag_get_document_assets`：
- 问题涉及图、表、截图、扫描件、页面图片或视觉内容
- 搜索结果里的 `assets` 对回答有帮助
- 需要获取图片的 `image_url`、`caption_or_ocr`、页码或 block 信息
- 文档预览或 chunk 文本引用了图片，但需要查看实际图片 URL

## Subagent 指南

如果 `task` 工具可用，仅在主题具有相互独立的维度时，才使用 subagent 并行开展本地研究。

合适的 subagent 委派：
- 一个 subagent 梳理架构和实现细节。
- 一个 subagent 调查 API 和集成点。
- 一个 subagent 审查限制、风险或开放问题。

每个 subagent 必须：
1. 优先搜索本地知识库。
2. 返回相关的 `document_id` 值。
3. 总结关键证据和置信度。
4. 将任何来自网页的信息标记为外部补充。

不要为简单的单次查询查找使用 subagent。

## 质量标准

当你能够自信回答以下问题时，研究才算充分：

- 本地语料如何定义这个主题？
- 哪些文档支撑主要判断？
- 关键组件、工作流或概念是什么？
- 有哪些具体示例或实现细节？
- 是否存在相关图表、截图、扫描页或 OCR 证据？
- 本地语料没有回答什么？
- 如果使用了有限网页研究，补充了哪些内容？

## 常见错误

- 一次 `rag_search` 后就停止
- 把片段当作强判断的充分证据
- 不阅读任何完整文档预览
- 忽略 `assets`、`image_url`、`caption_or_ocr` 和 `from_chunk_ids`
- 把 `image_abs` 暴露给用户
- 将 OCR/caption 当成完全可靠的事实
- 混合本地证据和网页证据，却不标明区别
- 在穷尽明显本地查询前就使用网页搜索
- 忽略薄弱或矛盾的本地证据
- 证据缺口尚未解决时，就产出精致但依据不足的回答

## 输出

完成本地深度研究后，生成的回答应包括：

1. 简明的直接回答或执行摘要
2. 按研究角度组织的关键发现
3. 使用文档标题、文件名、`document_id`、chunk id、页码或 asset id 给出的本地证据引用
4. 如果使用过网页工具，给出外部补充上下文
5. 不确定性、缺口或建议的后续搜索

### 推荐引用格式

关键判断后使用简短来源标注，例如：

```text
该系统通过线程运行接口进行流式交互。[本地证据：thread_runs 文档，document_id=..., chunk=42]
```

如果使用图片或 OCR 证据：

```text
架构图显示网关位于前端和 LangGraph 服务之间。[本地证据：architecture 文档，asset=17，OCR/caption]

![架构图](image_url)
```

引用要求：

- 不要伪造来源编号、页码、chunk id 或 asset id。
- 如果只有 OCR/caption 支撑，明确说明这是图片 OCR/说明，不要写成确定事实。
- 如果本地证据不足，直接说明不足，并列出已经检索过的角度或建议的下一步查询。
- 网页信息只能作为“外部补充”，不能覆盖本地证据中的明确内容。

只有在此之后，才继续内容生成或最终建议。
