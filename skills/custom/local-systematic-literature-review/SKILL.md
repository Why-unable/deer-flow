---
name: local-systematic-literature-review
description: 当用户要求基于本地知识库中的多篇论文、报告、标准或技术文档做深度研究报告、完整研究报告、全部/所有相关文档报告、系统性文献综述、survey、literature review、annotated bibliography、跨文档方法比较、主题综合或研究趋势分析时使用此 skill。它不访问 arXiv，而是使用 rag_list_documents、rag_search、rag_get_document、rag_get_document_preview、rag_get_document_chunks 和 rag_get_document_assets 对 MMKB 本地文档进行筛选、抽取和综合。单篇文档总结不要使用此 skill。
---

# 本地系统性文献综述 Skill

## 概览

此 skill 用于基于 MMKB 本地知识库做系统性文献综述（Systematic Literature Review, SLR）或多文档 survey。

它充分借鉴公开版 `systematic-literature-review` 的结构化综述方法，但数据源不同：

- 公开版：搜索 arXiv，抽取论文元数据，生成 APA/IEEE/BibTeX 报告。
- 本地版：搜索 MMKB 本地知识库，筛选已上传文档，抽取本地证据，生成可追溯的本地综述报告。

核心目标不是“列出几篇文档”，而是对多篇本地文档进行：

1. 明确纳入/排除标准；
2. 统一字段抽取；
3. 跨文档主题综合；
4. 共识、分歧和缺口分析；
5. 本地证据引用。

## 何时使用

当用户目标是构建多文档候选集合、筛选来源、跨文档综合、生成完整本地研究报告，或使用系统综述方法时，使用此 skill。适用请求包括：

- “基于本地知识库做一个文献综述”
- “基于本地全部文档做一个深度研究报告”
- “综合所有相关本地文档，生成完整研究报告”
- “survey 本地这些论文/报告”
- “比较本地知识库中几篇文档的方法”
- “综合多篇本地 NIST 文档，并分析它们的共识、分歧和缺口”
- “做一个 annotated bibliography”
- “本地文档中关于 X 的研究趋势是什么”
- “综合多个本地资料，写一个系统性综述”
- “对本地知识库里的几篇论文做 SLR”
- “围绕 X 做主题综合报告”

不要在以下情况使用：

- 用户只要求总结单篇文档。应使用普通本地阅读或 `local-deep-research`。
- 用户只是问一个事实问题，不需要多文档综合。
- 用户明确要求搜索公开 arXiv 或外部论文库。应使用公开版 `systematic-literature-review` 或 web 工具。
- 用户要求单篇论文 peer review。应使用 `academic-paper-review`。
- 用户要求一般本地深度研究，但不强调多篇文档综述、文献矩阵或跨文档比较。应使用 `local-deep-research`。

## 与 local-deep-research 的边界

`local-deep-research` 是通用本地研究流程，适合回答一个复杂问题。

`local-systematic-literature-review` 是多文档综述流程，适合需要构建文档集合、筛选来源、抽取统一字段并综合主题的任务。

如果用户的问题同时满足：

- 需要本地知识库；
- 涉及多篇文档；
- 需要完整报告、深度研究报告、全部/所有相关文档报告、研究趋势、主题综合、survey / literature review / systematic review / annotated bibliography / 跨文档方法比较；

则优先使用此 skill。

## 本地路径禁用规则

本地综述只能通过 `rag_*` 工具读取 MMKB 文档内容。允许使用的读取路径是：`rag_list_documents`、`rag_search`、`rag_get_document`、`rag_get_document_preview`、`rag_get_document_chunks`、`rag_get_document_assets`、`rag_get_document_asset` 和 `rag_list_collections`。

禁止把 MMKB 返回的 `input_file_path`、`markdown_merged_path`、`markdown_image_dir_path`、`md_asset_base`、`image_abs` 或任何 `/home/.../storage/...`、`documents/.../markdown/...` 一类路径交给 `grep`、`read_file`、`bash`、`ls` 等文件/命令工具。那些路径是 MMKB 服务端元数据或 URL 线索，不是 DeerFlow sandbox 内可读文件。需要正文时用 `rag_get_document_preview` 或 `rag_get_document_chunks`；需要图片时用 `rag_get_document_assets` 或 `rag_search` 返回的 `image_url`。

面向用户输出本地文档或图片链接时，优先使用 `rag_*` 工具返回的
`document_url`、`image_url` 等现成 URL，并逐字保留这些 URL。工具未返回 URL 时，
展示标题与证据 ID 作为来源追踪信息。

如果 `rag_get_document_preview` 返回 `truncated=true`，该结果只代表文档部分预览。
对于纳入/排除判断、统一字段抽取、方法/结果/局限总结或最终报告中的强结论，
应优先使用 `rag_get_document_chunks` 或进行更有针对性的 `rag_search` 覆盖后续
章节。只有当前预览不足以建立文档概览，例如目录、章节结构或开头背景不完整时，
才通过提高 `max_chars`，或使用上一轮返回的 `end_char` 作为 `start_char`
继续读取下一段 preview 来补足概览。只有在报告中明确标注为初步分析
时，才可把截断 preview 作为主要依据。

## 子任务派发与汇总约束

使用 `task` 批量抽取时，subagent 返回值必须服务于后续综述矩阵，而不是只给自然语言概述。派发 prompt 应要求每篇文档返回统一字段、文本证据位置和视觉证据字段。

视觉证据字段包括 `asset_id`、`page_id`、`block_id`、简短 OCR/caption 摘要，以及从 `rag_search`、`rag_get_document_assets` 或 `rag_get_document_asset` 逐字复制的完整 `image_url`。每篇文档的来源字段同时保留 `document_id`、标题和 `document_url`。没有可用 `image_url` 时，只返回 `asset_id`、页码和 OCR/caption 摘要，不输出 Markdown 图片。

派发 prompt 应明确禁止根据 `document_id`、preview Markdown、`md_images/...`、`image_abs`、`/api/documents/.../media/...` 或服务端路径拼接图片 URL；来源文档字段使用工具返回的 `document_url`。

汇总阶段必须保留每篇纳入文档的抽取结构、证据矩阵和关键图表字段。用户要求完整综述或深度研究报告时，不要把 subagent 的逐篇结果压缩成只剩 executive summary；跨文档主题综合应建立在保留下来的逐篇证据之上。

对使用 subagent 的综述，必须采用中间文件协议：

```text
research-notes/slr-batch-<n>.json
```

每个 subagent 必须把该批次的完整抽取结果写入中间文件，并在 task 返回中报告文件路径、覆盖文档数量、失败文档和简短摘要。主 agent 在进入跨文档综合前，必须用 `read_file` 读取所有 batch 文件，以文件内容作为证据矩阵和最终报告的主要输入；不要只依赖 task 返回摘要。

如果某个 batch 文件缺失、不可读或不是预期结构，记录该批次为不完整证据，不要把摘要扩写成完整抽取结果。

## 工作流

严格按以下阶段执行。

### 阶段 0：Skill 状态展示

当你决定本轮采用此 skill 时，在其它研究工具调用前先调用：

```text
report_active_skill(skill_name="local-systematic-literature-review")
```

该工具只记录本轮使用的 skill，供客户端在 `reasoning_content` 中显示；它不执行研究、不加载 skill，也不替代后续检索、筛选和报告生成流程。

### 阶段 1：确认范围

开始检索前，确认以下信息。如果缺失且会影响结果，最多问一个澄清问题，不要一项一项追问。

- **主题**：综述围绕什么主题或问题。
- **文档范围**：默认最多纳入 15 篇/份文档；不是必须凑满 15 篇。用户可指定数量，但建议不超过 20。
- **文档类型**：是否限定论文、标准、NIST 文档、报告、技术白皮书、某个 collection 等。
- **输出形式**：默认 Markdown 报告；如果用户要求，可生成 annotated bibliography、证据矩阵、执行建议版综述等。
- **引用偏好**：默认使用本地证据引用，不假装生成 APA/IEEE/BibTeX；只有当本地文档元数据足够支持时，才可附加类 APA/IEEE 参考列表。
- **输出位置**：默认保存到 `/mnt/user-data/outputs/`。

默认值：

```text
文档数量：最多 15
输出格式：Markdown
引用方式：本地证据引用
保存目录：/mnt/user-data/outputs/
```

如果用户给出的范围过大，例如“综述全部文档”或“50 篇以上”，应说明本地综述质量会随文档数量下降，建议先按主题、collection、时间范围或文档类型拆分。

### 阶段 1.5：研究计划产物

进入候选发现前，先形成一份内部 `research_plan`，后续检索、筛选、抽取和报告都围绕它执行。计划至少包含：

- 研究主题和用户问题；
- 文档范围、默认纳入上限和任何 collection/type 限制；
- 2-5 个检索 query 或 query 变体；
- 纳入/排除标准；
- 是否需要 subagent，以及批次策略；
- 预期最终报告结构；
- 可能需要检查的视觉证据类型。

如果任务会生成完整报告，最终报告的 Methodology 部分应概述这份计划，而不是只展示最终结论。

### 阶段 2：发现候选文档

使用本地 RAG 工具发现候选文档。不要使用 arXiv 脚本。

推荐顺序：

1. `rag_list_documents(limit=100, offset=0, collection_id=<optional>)`：了解 ready 文档池。该工具只返回轻量元数据和分页信息，不返回正文；当 `has_more=true` 时，可用 `next_offset` 继续翻页。
2. `rag_search(query="<topic>", mode="hybrid", limit=10)`：获取主题相关 chunks/assets。
3. 使用 2-5 个查询变体继续搜索：
   - 中文关键词；
   - 英文关键词；
   - 缩写和全称；
   - 具体方法名、框架名、标准名；
   - 用户提到的文档标题或领域词。
4. 如用户提到集合、项目、文件夹、类别，调用 `rag_list_collections` 做范围确认，并在后续 `rag_list_documents` 中传入对应 `collection_id`。

大文档库处理规则：

- 如果用户没有明确研究主题，且 `rag_list_documents` 显示 ready 文档超过 20 篇，不要直接开始完整综述。最多列出 20 篇候选标题、collection、更新时间和页数/chunk 数，询问用户要研究的主题、collection 或具体文档范围。
- 如果用户已经给出明确主题，先使用 2-5 个 `rag_search` 查询变体发现相关文档；若候选文档超过 20 篇，列出最相关的 20 篇让用户确认范围。
- 如果 `rag_search` 返回很多 chunk 但只涉及少量文档，应尝试同义词、缩写、中英文、标题关键词和 collection 范围补充候选。若仍然只找到少量相关文档，明确说明实际可检索到的相关文档数量，不要为达到默认上限而补造或硬凑文档。
- `rag_list_documents` 的标题/collection 信息可辅助发现候选，但不替代正文阅读；进入纳入/排除和抽取阶段后，仍需使用 `rag_get_document_preview`、`rag_get_document_chunks` 或针对性 `rag_search`。

查询原则：

- 不要只做一次 `rag_search` 就进入综合。
- 宽泛主题先用 broad query，随后用更具体 query 验证。
- 对英文论文/标准，同时尝试英文关键词。
- 对中文问题，保留中文查询，同时补充英文术语。
- 如果初始检索为 0，尝试更短关键词、英文/中文互换、缩写展开。

候选文档去重：

- 根据 `document_id` 去重。
- 记录每个候选文档来自哪些查询、命中的 chunks/assets、标题和页码。
- 不要把同一文档的多个 chunk 误当作多篇文献。

### 阶段 3：纳入/排除筛选

构建候选文档清单后，按明确标准筛选。

纳入标准示例：

- 与用户主题直接相关；
- 文档状态为 ready；
- 有足够 preview/chunk 内容可读；
- 在多个查询中反复出现；
- 是用户指定类型，例如 NIST 文档、论文、标准、报告；
- 能提供方法、发现、框架、建议或证据。

排除标准示例：

- 只弱相关或只出现一个泛词；
- 文档内容过少，无法支持综述判断；
- 与主题不同领域同名；
- 重复文档；
- 只包含图片/OCR 且无法可靠抽取关键信息；
- 用户指定范围之外。

对每篇候选文档，至少使用：

```text
rag_get_document(document_id)
rag_get_document_preview(document_id, max_chars=12000, start_char=0)
```

必要时使用：

```text
rag_get_document_chunks(document_id)
rag_get_document_assets(document_id)
rag_get_document_asset(document_id, asset_id)
```

`rag_get_document_assets` 仅用于浏览分页紧凑资产目录；`has_more=true` 时按
`next_page` 继续浏览。若要使用某项资产的完整 OCR、
metadata 或在最终正文中展示其图片，必须再调用 `rag_get_document_asset`，并逐字
复制单资产详情返回的完整签名 URL。

若 `rag_get_document_preview` 返回 `truncated=true`，候选筛选阶段可以先用它判断
相关性，但纳入文档进入统一字段抽取或最终证据矩阵前，应补充
`rag_get_document_chunks` 或用针对性查询覆盖关键后续章节；只有概览信息不足时，
才提高 `max_chars`，或用上一轮返回的 `end_char` 作为 `start_char`
继续读取下一段 preview。不要把仅基于部分 preview 的判断描述成已
覆盖全文。

筛选输出应在内部形成一张矩阵：

| 字段 | 含义 |
|---|---|
| `document_id` | MMKB 文档 ID |
| `document_url` | 工具返回的 MMKB 文档页面链接 |
| 标题/文件名 | 人类可读来源名 |
| 文档类型 | 论文、标准、指南、报告、白皮书等 |
| 匹配查询 | 哪些 query 找到它 |
| 纳入/排除 | include / exclude |
| 原因 | 为什么纳入或排除 |
| 证据位置 | chunk id、页码、asset id、preview 线索 |

如果本地候选文档少于用户要求，应明确说明实际可用数量，不要补造来源。

### 阶段 4：统一字段抽取

对纳入文档做统一字段抽取。目标是让不同文档可以被横向比较。

每篇文档至少抽取：

```json
{
  "document_id": "...",
  "document_url": "...",
  "title": "...",
  "source_ext": "pdf",
  "document_type": "paper | standard | guide | report | whitepaper | unknown",
  "main_topic": "...",
  "purpose_or_research_question": "...",
  "methodology_or_framework": "...",
  "key_findings": ["...", "..."],
  "recommendations_or_implications": ["...", "..."],
  "limitations_or_scope": "...",
  "evidence": [
    {
      "chunk_id": "...",
      "page": "...",
      "quote_or_summary": "...",
      "asset_id": "...",
      "image_url": "..."
    }
  ]
}
```

证据要求：

- 每篇文档至少保留 1-3 条关键本地证据。
- 证据应尽量包含 `document_url`、`document_id`、chunk id、页码或 asset id。
- 不要复制大段原文；使用简短摘录或转述。
- 如果判断来自 OCR/caption，要明确标记为视觉/OCR 证据。
- 如果 preview 曾返回 `truncated=true`，记录后续补读方式；未补读时把该文档标记为证据覆盖不足，不作为全文级强结论的唯一依据。

#### 是否使用 subagent

如果 `task` 工具可用，且纳入文档超过 5 篇，必须优先使用 subagent 批量抽取；如果 subagent 不可用或某批次失败，主 agent 必须直接完成受影响文档的逐篇抽取，或者在报告中明确降级为初步分析并列出缺失批次。

批次策略：

| 纳入文档数 | 批次 | 轮次 |
|---|---|---|
| 1-5 | 1 批 | 主 agent 直接抽取或 1 个 subagent |
| 6-10 | 2 批 | 1 轮，最多 2 个 subagent |
| 11-15 | 3 批 | 1 轮，最多 3 个 subagent |
| 16-20 | 4 批 | 2 轮，3 + 1 |

同一轮不要派发超过 3 个 subagent。

subagent prompt 应包含：

```text
请基于以下 MMKB 本地文档材料抽取结构化综述元数据。
只使用给定材料，不要搜索外部网页，不要编造来源。
将完整 JSON array 写入 research-notes/slr-batch-<n>.json。
task 返回中只报告：中间文件路径、覆盖文档数量、失败文档、3-5 条摘要。完整抽取结果以文件为准。

对每篇文档返回 JSON 对象：
- document_id
- document_url
- title
- document_type
- main_topic
- purpose_or_research_question
- methodology_or_framework
- key_findings
- recommendations_or_implications
- limitations_or_scope
- evidence: [{chunk_id, page, quote_or_summary, asset_id, page_id, block_id, caption_or_ocr_summary, image_url}]

如涉及视觉证据，image_url 使用工具返回或 subagent 已逐字带回的 image_url；来源文档链接使用工具返回的 document_url。

资源预算（必须遵守，防止耗尽步数）：
- 每篇文档最多取 1 张关键图；本批次 rag_get_document_asset 全程 ≤ 3 次。
- 文字证据（chunk / OCR 摘要）足够时不取图，只填 asset_id + caption_or_ocr_summary。
- 不要遍历文档全部资产目录；rag_get_document_assets 每篇最多翻 1-2 页。
- 检索点到为止：每篇文档 rag_search / preview / chunks 合计控制在 ~8 次内。
- **步数将尽时（接近上限），立即用已抽取到的内容写入中间文件并返回**，
  返回里标明哪些文档未完成；绝不允许因为没抽完就不写文件、不返回。

只返回 JSON array，不要输出 markdown fence 或解释性前言。
```

派发 prompt 中的“只返回 JSON array”指写入中间文件的内容；task 返回可以是简短状态说明，但必须包含中间文件路径。

如果 subagent 返回不可解析内容，应记录受影响文档，并继续处理其它批次。不要因为一个批次失败就编造结果。

### 阶段 4.5：检索收敛与资源预算（硬约束，必须遵守）

本阶段是**强制止损与收敛点**。综述任务最常见的失败是：agent 不停检索、逐张拉取
图片资产，耗尽步数（撞 `Recursion limit reached`），导致报告永远生成不出来。为避免
此问题，进入阶段 5 之前必须满足以下硬性预算，任一超限都要**立即停止检索/取图，转入报告生成**：

**检索收敛条件（满足其一即停止一切检索）：**

- 候选文档已覆盖用户主题的主要维度（纳入文档已能支撑 3-6 个主题）；
- 或 `rag_search` 累计调用已达约 15-20 次；
- 或最近 2-3 次检索没有再带来新的相关文档 / 新证据（收益递减）。

一旦满足，**禁止再发起新的 `rag_search`**，直接用已收集的证据进入阶段 5 写报告。
宁可在报告的「局限」里说明"某维度证据有限"，也不要为凑证据无限检索。

**图片资产硬预算（这是耗 token 大户，必须卡死）：**

- 整份综述**最多获取 8 张图**（`rag_get_document_asset` 全程调用 ≤ 8 次）。
- **只对已确定要放进报告正文的图**调用 `rag_get_document_asset` 取详情；
  不要遍历文档的全部资产目录，不要"先全拉下来再挑"。
- `rag_get_document_assets`（目录浏览）**最多翻 2-3 页**；能判断有没有可用图即可，
  不要为看完所有资产而反复翻页。
- 大多数文本型综述**根本不需要图**。只有当某个结论强依赖图表/架构图/截图时才取图；
  文字证据（chunk / OCR 摘要）已足够时，直接引用文字，不取图。
- 系统在引擎层对取图工具设了强制上限（超过约 12 次自动收尾）；主动遵守本预算，
  不要触发引擎兜底。

**报告必须产出（防止"宣布要写报告却没写"）：**

- 一旦进入阶段 5，**本轮唯一、最终的产物就是完整报告**。
- **禁止**用"让我现在生成最终报告""接下来我将整理综述"这类过渡语作为本轮结束。
  这类句子出现后，必须紧跟真正的报告内容；不允许把过渡语当成最终回复。
- 若使用了 subagent 写 `research-notes` 中间文件：主 agent 必须先 `read_file` 读回，
  再亲自把内容综合成最终报告。**subagent 失败或中间文件缺失时，主 agent 直接用
  已有证据写报告**，并在「局限」中标注该批次缺失——绝不能因 subagent 没跑完就不出报告。

### 阶段 5：跨文档综合

综合时必须超越逐篇摘要。最终报告至少包含：

- **研究范围和方法**：说明使用了哪些本地检索 query、纳入多少文档、排除多少文档。
- **主题 Themes**：3-6 个跨文档主题、方法路线或问题框架。
- **共识 Convergences**：多篇文档共同支持的结论。
- **分歧 Disagreements**：文档之间观点、方法、范围或建议的差异。
- **缺口 Gaps**：本地文档没有覆盖或证据不足的内容。
- **实践含义 Implications**：如果用户关心落地，说明这些文档共同指向什么行动。
- **证据矩阵**：列出每篇纳入文档的主题、关键发现和证据。

如果文档集合太小或异质性太高，无法形成可靠主题，应明确说明，不要强行编造主题。

生成最终 Markdown 或文件前，检查所有图片链接和本地资源链接。MMKB 图片只保留逐字复制的 `image_url`；无法确认来自工具结果或 subagent 结构化字段的链接，改为文字证据标注或省略。不要根据路径形态自行修复链接，需要图片时重新调用 `rag_get_document_asset`。

跨文档综合前，必须读取所有 `research-notes/slr-batch-*.json` 中间文件，并把读取到的逐篇抽取结果合并为证据矩阵。最终报告的方法部分应说明使用了多少个 batch 文件，以及是否存在缺失或不可读的 batch。

### 阶段 6：质量门槛和自检修订

生成最终报告前，必须执行一次质量自检。检查项包括：

- 是否有 `research_plan`，且报告 Methodology 能反映计划；
- 是否形成候选文档清单和纳入/排除记录；
- 是否对每篇纳入文档完成统一字段抽取；
- 如果使用 subagent，是否已读取所有中间文件，而不是只依赖 task 返回摘要；
- 是否处理了所有 `truncated=true` 的 preview，并对纳入文档补读 chunks、做针对性检索，或标注证据覆盖不足；
- 是否有 evidence matrix，且关键结论能回到文档、chunk、页码或 asset；
- 是否检查并清理了不合规图片/资源链接；
- 报告是否满足长度和密度要求。

若任一关键项缺失，不要把结果命名或描述为“完整深度研究报告”。应修订补齐；确实无法补齐时，在标题、Executive Summary 或 Methodology 中明确标记为“初步分析”，并列出缺失原因。

### 阶段 7：长度和密度预算

完整本地综述或深度研究报告应有足够展开度，除非可用证据不足：

- Executive Summary：3-5 句，只综合不逐篇罗列；
- Methodology：说明检索 query、候选数量、纳入/排除标准和批次/中间文件情况；
- Included Documents：每篇纳入文档至少有一行纳入原因；
- Themes：3-6 个主题，每个主题至少包含 2 条本地证据或说明为何证据不足；
- Convergences / Disagreements / Gaps：分别给出可追溯证据或明确缺口；
- Evidence Matrix：每篇纳入文档至少一行，包含关键发现、方法/框架、局限和证据位置；
- Visual Evidence：如使用图片或 OCR/caption，列出 `document_id`、`asset_id`、页码、摘要和逐字复制的 `image_url`；没有可用 `image_url` 时只保留文字证据位置。

当纳入文档不少于 3 篇时，完整报告通常不应只有几段摘要。若最终内容明显偏短，先补充逐文档抽取、主题证据和矩阵，再保存报告。

### 阶段 8：引用和报告格式

默认使用本地证据引用，不使用 arXiv APA/IEEE/BibTeX 规则。本地证据引用优先写成可点击 Markdown 链接，并在链接后保留必要的追踪字段。

在正文中列出具体本地文档标题、论文名或资料名时，如果工具结果提供了 `document_url`，使用 `[文档标题](document_url)`；如果只是概括领域、类别或数量，可以不加链接。

推荐引用格式：

```text
[本地证据：<title>](<document_url>)；document_id=<id>；chunk=<chunk_id>；page=<page>
```

如涉及视觉证据：

```text
[视觉证据：<title>](<document_url>)；document_id=<id>；asset=<asset_id>；page=<page>
```

如果文档 metadata 足够完整，且用户明确要求 APA/IEEE/BibTeX，可以在报告末尾附加“近似参考格式”。但必须说明：

```text
以下参考格式基于本地文档元数据生成，可能缺少作者、出版年份或正式出版信息。
```

不要把没有作者/年份/出版源的本地文件伪装成正式论文引用。

### 阶段 9：保存和展示

完整报告保存到：

```text
/mnt/user-data/outputs/local-slr-<topic-slug>-<YYYYMMDD>.md
```

保存后调用 `present_files`，让用户下载。

聊天中只展示简短预览：

1. 3-5 句 executive summary；
2. themes 名称和一句话解释；
3. 纳入/排除文档数量；
4. 报告文件名。

不要在聊天中直接粘贴完整长报告。完整证据矩阵、逐文档注释和参考列表应放入文件。

## 报告结构模板

最终 Markdown 报告使用以下结构：

```markdown
# 本地系统性文献综述：<主题>

**日期**：<YYYY-MM-DD>
**本地知识库**：MMKB
**纳入文档数**：<N>
**候选文档数**：<M>
**引用方式**：本地证据引用

## Executive Summary

<3-5 句话综合说明，不要逐篇罗列。>

## Methodology

本综述基于 MMKB 本地知识库，使用以下查询发现候选文档：

- `<query 1>`
- `<query 2>`
- `<query 3>`

纳入标准：
- <criterion>

排除标准：
- <criterion>

局限性：
- 本综述只覆盖当前 MMKB 中已上传且 ready 的文档。
- 文档 metadata 可能缺少作者、年份或正式出版信息。
- OCR/caption 证据可能存在识别误差。

## Included Documents

| 文档 | 类型 | document_id | 纳入原因 |
|---|---|---|---|
| ... | ... | ... | ... |

## Excluded Candidates

| 文档 | document_id | 排除原因 |
|---|---|---|
| ... | ... | ... |

## Themes

### Theme 1: <主题名>

<跨文档综合说明，包含本地证据引用。>

### Theme 2: <主题名>

<...>

## Convergences and Disagreements

**共识**：

- <多篇文档共同支持的结论> [本地证据：...]

**分歧**：

- <文档之间的差异> [本地证据：...]

## Gaps and Open Questions

- <本地文档没有覆盖或证据不足的点>

## Evidence Matrix

| 文档 | 关键发现 | 方法/框架 | 局限 | 证据 |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

## Visual Evidence

| 文档 | asset/page | OCR/caption 摘要 | image_url 或证据位置 |
|---|---|---|---|
| ... | ... | ... | ... |

## Quality Check

- research_plan：<已完成/缺失>
- 候选与筛选记录：<已完成/缺失>
- 中间文件读取：<N 个 batch，或说明未使用 subagent>
- evidence matrix：<已完成/缺失>
- 图片/资源链接检查：<已完成/无图片/已移除不合规链接>
- 报告完整性：<完整报告/初步分析，并说明原因>

## Per-Document Annotations

### <文档标题>

- `document_id`: <id>
- 来源链接：[<文档标题>](<document_url>)
- 类型：<type>
- 主题：<main_topic>
- 目的/问题：<purpose_or_research_question>
- 方法/框架：<methodology_or_framework>
- 关键发现：
  - ...
- 局限/范围：
  - ...
- 本地证据：
  - [本地证据：<文档标题>](<document_url>)；chunk=...；page=...

## References / Local Sources

- [<title>](<document_url>) (`document_id=<id>`)
```

## 常见失败模式

避免以下错误：

- 只做一次 `rag_search` 就生成综述。
- 把 chunk 当作文档，导致同一文档重复计数。
- 没有纳入/排除标准。
- 只逐篇摘要，没有跨文档主题综合。
- 把本地文件伪装成正式 arXiv/APA/IEEE 文献。
- 忽略 `assets` 中的视觉证据。
- 展示服务端本地路径或 `image_abs` 给普通用户。
- 在本地证据不足时仍给出强结论。
- 在聊天正文中输出完整长报告而不是保存文件。

## 示例

### 示例 1：NIST 本地文档综述

用户：

```text
请基于本地知识库中的 NIST 文档，做一个关于小企业使用 CSF 2.0 的系统性综述。
```

流程：

1. 使用 `rag_list_documents` 发现 ready 文档。
2. 搜索：
   - `NIST CSF 2.0 small business`
   - `Cybersecurity Framework small business`
   - `CSF 2.0 implementation guide`
3. 筛选 NIST 相关文档。
4. 对纳入文档读取 preview/chunks/assets。
5. 抽取目标、框架、关键建议、适用范围、局限。
6. 综合 themes，例如治理、资产识别、保护措施、响应恢复、供应链风险。
7. 保存 `local-slr-nist-csf-small-business-<YYYYMMDD>.md`。

### 示例 2：本地论文 survey

用户：

```text
请比较本地知识库中几篇关于 RAG 的论文，整理它们的方法、发现和局限。
```

流程：

1. 搜索 `retrieval augmented generation`、`RAG`、`agentic RAG`。
2. 去重 document_id。
3. 判断哪些是真正论文，排除无关报告。
4. 对每篇论文抽取 methodology、key_findings、limitations。
5. 综合方法分类、共同发现、分歧和未来缺口。

## 备注

- 此 skill 不访问 arXiv，不调用 `arxiv_search.py`。
- 此 skill 的事实来源是 MMKB 本地知识库。
- 如果用户要求结合外部最新论文，应先说明本地综述范围，再使用 web/arXiv 作为单独外部补充。
- 如果 `task` 工具不可用，仍可做小规模本地综述，但应把文档数量控制在 5 篇以内，避免上下文过载。
