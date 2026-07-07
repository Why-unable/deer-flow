---
name: local-deep-research
description: 当用户需要基于本地知识库回答一个具体问题、解释一个主题、分析某个概念/系统/文档集，或生成基于本地证据的普通研究回答时使用此 skill。优先使用 rag_search、rag_get_document、rag_get_document_preview、rag_get_document_chunks 和 rag_get_document_assets。若用户要求深度研究报告、完整研究报告、基于全部/所有相关本地文档的报告、研究趋势、主题综合、系统性文献综述、survey、annotated bibliography、多篇论文/报告的跨文档方法比较、纳入/排除筛选或证据矩阵，应改用 local-systematic-literature-review。
---

# 本地深度研究 Skill

## 概览

当本地文档应作为主要事实来源时，此 skill 提供一套系统化方法，用于开展基于本地知识库的充分研究。**在开始普通本地深度研究回答或内容生成任务前，先加载此 skill**。

如果用户要求深度研究报告、完整研究报告、基于全部/所有相关本地文档的报告、研究趋势、主题综合、系统性文献综述、survey、annotated bibliography、多篇论文/报告的跨文档方法比较、纳入/排除筛选或证据矩阵，应使用 `local-systematic-literature-review`，而不是此 skill。

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
- 用户要求“深度研究报告”“完整研究报告”“基于本地全部文档/所有相关文档”“研究趋势报告”或“主题综合报告”，即使没有写出 SLR、literature review 或 survey。

以上情况使用 `local-systematic-literature-review`。

## 核心原则

### Skill 状态展示

当你决定本轮采用此 skill 的完整或轻量本地研究流程时，在其它研究工具调用前先调用：

```text
report_active_skill(skill_name="local-deep-research")
```

该工具只记录本轮使用的 skill，供客户端在 `reasoning_content` 中显示；它不执行研究、不加载 skill，也不替代后续 RAG 工具调用。若只是普通直接回答且未采用此 skill，不要调用。

### 轻量本地问答路径

当用户只需要基于本地知识回答一个明确问题、解释一个主题或获得简要概述时，使用最短且充分的检索路径：

1. 默认先调用一次 `rag_search(query="<topic>", mode="hybrid", limit=10)`。
2. 如果命中的 chunks/assets 已足以支持可靠回答，直接综合并回答。
3. 只有在检索片段缺少必要上下文、需要精确证据或涉及视觉细节时，才继续调用 `rag_get_document_preview`、`rag_get_document_chunks` 或视觉资产工具。
4. 如果 `rag_get_document_preview` 返回 `truncated=true`，且当前预览不足以了解文档概览，例如目录、章节结构或开头背景不完整，可以提高 `max_chars`，或使用上一轮返回的 `end_char` 作为 `start_char` 继续读取下一段 preview；若用户问题涉及全文、整篇、完整总结、方法、实验、结果、局限或其它需要覆盖后续章节的判断，优先使用 `rag_get_document_chunks` 或更有针对性的 `rag_search` 后再回答。
5. 不要把 `rag_list_documents` 当作普通主题查询的固定前置步骤；它用于文档清单、范围发现、按 `collection_id` 缩小文档池，或多文档综述候选池。
6. 除非用户明确要求报告、文件或可下载交付物，否则直接在聊天正文中回答，不默认生成文件。

### 本地路径禁用规则

本地知识库文档内容只能通过 `rag_*` 工具读取。允许使用的读取路径是：`rag_search`、`rag_list_documents`、`rag_get_document`、`rag_get_document_preview`、`rag_get_document_chunks`、`rag_get_document_assets`、`rag_get_document_asset` 和 `rag_list_collections`。

禁止把 MMKB 返回的 `input_file_path`、`markdown_merged_path`、`markdown_image_dir_path`、`md_asset_base`、`image_abs` 或任何 `/home/.../storage/...`、`documents/.../markdown/...` 一类路径交给 `grep`、`read_file`、`bash`、`ls` 等文件/命令工具。那些路径是 MMKB 服务端元数据或 URL 线索，不是 DeerFlow sandbox 内可读文件。需要正文时用 `rag_get_document_preview` 或 `rag_get_document_chunks`；需要图片时用 `rag_get_document_assets` 或 `rag_search` 返回的 `image_url`。

面向用户输出本地文档或图片链接时，优先使用 `rag_*` 工具返回的
`document_url`、`image_url` 等现成 URL，并逐字保留这些 URL。工具未返回 URL 时，
展示标题与证据 ID 作为来源追踪信息。

### 子任务派发与汇总约束

当你使用 `task` 派发本地研究子任务时，派发 prompt 应要求 subagent 返回结构化证据，而不是只给一段概述。至少包括：

- `document_id`、标题或文件名、`document_url`；
- 相关 chunk id、页码或其它文本证据位置；
- 关键发现、证据强度和仍不确定的点；
- 如涉及视觉证据，返回 `asset_id`、`page_id`、`block_id`、简短 OCR/caption 摘要，以及从 `rag_search`、`rag_get_document_assets` 或 `rag_get_document_asset` 逐字复制的完整 `image_url`。

subagent 没有拿到可用 `image_url` 时，只返回视觉证据位置，不输出 Markdown 图片。派发 prompt 也应明确：不得根据 `document_id`、preview Markdown、`md_images/...`、`image_abs`、`/api/documents/.../media/...` 或服务端路径拼接图片 URL；需要展示来源文档时保留工具返回的 `document_url`。

汇总 subagent 结果时，保留每篇/每个维度的核心结构和证据矩阵；用户要求深度报告时，不要把多个 subagent 的研究结果压缩成只剩几段摘要。最终报告中的图片只能使用工具结果或 subagent 结构化字段里已经逐字带回的 `image_url`；无法确认来源的图片链接应改为文字证据标注或省略。

对会生成最终报告的本地深度研究，subagent 必须把完整结果写入共享工作区中间文件，推荐路径：

```text
research-notes/<task-slug>.md
```

派发 prompt 应明确要求 subagent：

1. 使用 `write_file` 写入完整研究记录，而不是只在 task 返回里给摘要。
2. 文件至少包含：任务范围、检索 query、涉及文档清单（含 `document_id`、标题和 `document_url`）、逐文档/逐维度发现、证据矩阵、视觉证据字段、关键缺口和低置信判断。
3. 视觉证据只写工具返回的 `image_url`，没有 `image_url` 时只写 `asset_id`、页码、OCR/caption 摘要。
4. task 返回中只报告中间文件路径、覆盖范围、主要发现和问题；完整内容以文件为准。

主 agent 生成最终报告前，必须先用 `read_file` 读取所有 subagent 返回的中间文件，并以文件内容作为主要汇总输入。不要只依赖 `task` 返回摘要；如果某个中间文件缺失或不可读，要在最终报告的方法/局限性中说明该批次证据不完整。

**当用户请求可以从本地知识库回答时，绝不要把通用知识或网页片段当作主要来源。**

输出质量取决于本地检索的广度、文档阅读的深度，以及证据综合的清晰度。对于明确要求深度研究的任务，单次 `rag_search` 通常不足；对于证据充分的轻量本地问答，可以直接综合并回答。

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
4. **阅读预览与必要补读**：对最重要的文档使用 `rag_get_document_preview`；若返回 `truncated=true` 且当前预览不足以建立概览，可以提高 `max_chars`，或用上一轮返回的 `end_char` 作为 `start_char` 继续读取下一段 preview；若任务需要覆盖后续章节或整篇证据，继续读取 `rag_get_document_chunks` 或用更精确 query 检索后续内容。
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
- rag_get_document_preview(document_id, max_chars=12000, start_char=0)
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
- `rag_get_document_preview` 返回 `truncated=true`，而用户问题需要全文、方法、实验、结果、局限或完整证据。

#### 何时使用 rag_get_document_assets

在以下情况使用 `rag_get_document_assets`：

- 用户问题涉及图片、图表、架构图、截图、扫描页、视觉布局或 OCR 内容。
- `rag_search` 返回了有价值的图片资产，需要查看更多同文档视觉证据。
- 文本证据提到了“如下图”“见图”“截图”“表格”“页面”等视觉线索。
- 需要发现可展示的视觉资产及其 `asset_id`、`image_url` 或 OCR 摘要。

`rag_get_document_assets` 返回的是分页紧凑资产目录，`caption_preview` 可能被截断；当 `has_more=true` 时按 `next_page` 继续浏览。选定需要深入分析或放入正文的资产后，必须调用 `rag_get_document_asset(document_id, asset_id)` 获取该资产的完整 `caption_or_ocr`、metadata 和签名 URL。面向用户输出图片时，只能逐字复制这次单资产详情调用返回的完整 URL。

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
- [ ] 如果 preview 返回 `truncated=true` 且问题需要后续章节或整篇证据，我是否已继续读取 chunks、进行针对性检索，或明确说明只基于已读取预览？
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

如果返回 `truncated=true`，说明当前只读到了文档的一段 preview 窗口。若当前预览不足以了解文档概览，例如目录、章节结构或开头背景不完整，可以提高 `max_chars`，或使用返回的 `end_char` 作为下一次 `start_char` 继续读取下一段 preview。对“全文讲了什么”、完整总结、方法、实验、结果、局限或其它需要后续章节证据的问题，继续调用 `rag_get_document_chunks` 或进行针对性检索；若仍只基于 preview 回答，应在答案中说明证据范围。

### 何时使用 rag_get_document_chunks

在以下情况使用 `rag_get_document_chunks`：
- 需要精确阅读某个文档的分块内容
- 需要验证检索命中的 chunk 是否被正确理解
- 需要使用 chunk id、页码或原文片段作为证据
- 需要把图片资产的 `from_chunk_ids` 映射回具体文本
- 已读 preview 被截断，但用户问题需要覆盖全文或关键后续章节

### 何时使用 rag_get_document_assets

在以下情况使用 `rag_get_document_assets`：
- 问题涉及图、表、截图、扫描件、页面图片或视觉内容
- 搜索结果里的 `assets` 对回答有帮助
- 需要浏览同一文档中的视觉资产目录、OCR 摘要、页码或 block 信息
- 文档预览或 chunk 文本引用了图片，但需要查看实际图片 URL

### 何时使用 rag_get_document_asset

在以下情况使用 `rag_get_document_asset(document_id, asset_id)`：
- 已从资产目录选中一张准备展示给用户的图片
- 需要完整 OCR/caption 或 metadata，而不是目录中的截断摘要
- 需要逐字复制一条完整签名 URL 到最终正文

## Subagent 指南

如果 `task` 工具可用，仅在主题具有相互独立的维度时，才使用 subagent 并行开展本地研究。

合适的 subagent 委派：
- 一个 subagent 梳理架构和实现细节。
- 一个 subagent 调查 API 和集成点。
- 一个 subagent 审查限制、风险或开放问题。

每个 subagent 必须：
1. 优先搜索本地知识库。
2. 返回相关的 `document_id` 值。
3. 返回 chunk id、页码、asset id 或其它可追溯证据位置。
4. 总结关键证据、证据强度和仍不确定的点。
5. 如涉及视觉证据，返回 `asset_id`、`page_id`、`block_id`、OCR/caption 摘要和逐字复制的完整 `image_url`；没有 `image_url` 时只返回证据位置，不输出 Markdown 图片。
6. 对最终报告相关任务，使用 `write_file` 将完整研究记录写入 `research-notes/<task-slug>.md` 或 `.json`，并在返回中给出该路径。
7. 将任何来自网页的信息标记为外部补充。

主 agent 在综合前必须读取这些中间文件：

```text
read_file("research-notes/<task-slug>.md")
```

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
3. 使用 `[文档标题](document_url)` 形式的本地证据引用，并在需要时补充 `document_id`、chunk id、页码或 asset id
4. 如果使用过网页工具，给出外部补充上下文
5. 不确定性、缺口或建议的后续搜索

在正文中列出具体本地文档标题、论文名或资料名时，如果工具结果提供了 `document_url`，使用 `[文档标题](document_url)`；如果只是概括领域、类别或数量，可以不加链接。

写入 Markdown 报告或最终文件前，检查所有图片链接：只保留从工具或 subagent 结构化字段逐字复制的 `image_url`。如果图片链接来自 preview Markdown、相对路径、服务端路径或无法确认来源，不要尝试修复，改为保留文字证据标注或重新调用 `rag_get_document_asset` 获取正确 URL。

### 推荐引用格式

关键判断后使用简短来源标注，例如：

```text
该系统通过线程运行接口进行流式交互。[本地证据：thread_runs 文档](document_url)，document_id=..., chunk=42
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
