---
name: local-systematic-literature-review
description: 当用户要求基于本地知识库中的多篇论文、报告、标准或技术文档做系统性文献综述、survey、literature review、annotated bibliography、跨文档方法比较、主题综合或研究趋势分析时使用此 skill。它不访问 arXiv，而是使用 rag_list_documents、rag_search、rag_get_document、rag_get_document_preview、rag_get_document_chunks 和 rag_get_document_assets 对 MMKB 本地文档进行筛选、抽取和综合。单篇文档总结不要使用此 skill。
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

当用户提出以下类型请求时使用此 skill：

- “基于本地知识库做一个文献综述”
- “survey 本地这些论文/报告”
- “比较本地知识库中几篇文档的方法”
- “总结这些 NIST 文档/论文共同说明了什么”
- “做一个 annotated bibliography”
- “本地文档中关于 X 的研究趋势是什么”
- “综合多个本地资料，写一个系统性综述”
- “对本地知识库里的几篇论文做 SLR”

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
- 需要 survey / literature review / systematic review / annotated bibliography / 跨文档方法比较；

则优先使用此 skill。

## 本地路径禁用规则

本地综述只能通过 `rag_*` 工具读取 MMKB 文档内容。允许使用的读取路径是：`rag_list_documents`、`rag_search`、`rag_get_document`、`rag_get_document_preview`、`rag_get_document_chunks`、`rag_get_document_assets` 和 `rag_list_collections`。

禁止把 MMKB 返回的 `input_file_path`、`markdown_merged_path`、`markdown_image_dir_path`、`md_asset_base`、`image_abs` 或任何 `/home/.../storage/...`、`documents/.../markdown/...` 一类路径交给 `grep`、`read_file`、`bash`、`ls` 等文件/命令工具。那些路径是 MMKB 服务端元数据或 URL 线索，不是 DeerFlow sandbox 内可读文件。需要正文时用 `rag_get_document_preview` 或 `rag_get_document_chunks`；需要图片时用 `rag_get_document_assets` 或 `rag_search` 返回的 `image_url`。

## 工作流

严格按以下阶段执行。

### 阶段 1：确认范围

开始检索前，确认以下信息。如果缺失且会影响结果，最多问一个澄清问题，不要一项一项追问。

- **主题**：综述围绕什么主题或问题。
- **文档范围**：默认最多纳入 10 篇/份文档；用户可指定数量，但建议不超过 20。
- **文档类型**：是否限定论文、标准、NIST 文档、报告、技术白皮书、某个 collection 等。
- **输出形式**：默认 Markdown 报告；如果用户要求，可生成 annotated bibliography、证据矩阵、执行建议版综述等。
- **引用偏好**：默认使用本地证据引用，不假装生成 APA/IEEE/BibTeX；只有当本地文档元数据足够支持时，才可附加类 APA/IEEE 参考列表。
- **输出位置**：默认保存到 `/mnt/user-data/outputs/`。

默认值：

```text
文档数量：10
输出格式：Markdown
引用方式：本地证据引用
保存目录：/mnt/user-data/outputs/
```

如果用户给出的范围过大，例如“综述全部文档”或“50 篇以上”，应说明本地综述质量会随文档数量下降，建议先按主题或 collection 拆分。

### 阶段 2：发现候选文档

使用本地 RAG 工具发现候选文档。不要使用 arXiv 脚本。

推荐顺序：

1. `rag_list_documents(limit=...)`：了解 ready 文档池。
2. `rag_search(query="<topic>", mode="hybrid", limit=10)`：获取主题相关 chunks/assets。
3. 使用 2-5 个查询变体继续搜索：
   - 中文关键词；
   - 英文关键词；
   - 缩写和全称；
   - 具体方法名、框架名、标准名；
   - 用户提到的文档标题或领域词。
4. 如用户提到集合、项目、文件夹、类别，调用 `rag_list_collections` 做范围确认。

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
rag_get_document_preview(document_id, max_chars=12000)
```

必要时使用：

```text
rag_get_document_chunks(document_id)
rag_get_document_assets(document_id)
```

筛选输出应在内部形成一张矩阵：

| 字段 | 含义 |
|---|---|
| `document_id` | MMKB 文档 ID |
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
- 证据应尽量包含 `document_id`、chunk id、页码或 asset id。
- 不要复制大段原文；使用简短摘录或转述。
- 如果判断来自 OCR/caption，要明确标记为视觉/OCR 证据。

#### 是否使用 subagent

如果 `task` 工具可用，且纳入文档超过 5 篇，建议使用 subagent 批量抽取。

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

对每篇文档返回 JSON 对象：
- document_id
- title
- document_type
- main_topic
- purpose_or_research_question
- methodology_or_framework
- key_findings
- recommendations_or_implications
- limitations_or_scope
- evidence: [{chunk_id, page, quote_or_summary, asset_id, image_url}]

只返回 JSON array，不要输出 markdown fence 或解释性前言。
```

如果 subagent 返回不可解析内容，应记录受影响文档，并继续处理其它批次。不要因为一个批次失败就编造结果。

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

### 阶段 6：引用和报告格式

默认使用本地证据引用，不使用 arXiv APA/IEEE/BibTeX 规则。

推荐引用格式：

```text
[本地证据：<title>, document_id=<id>, chunk=<chunk_id>, page=<page>]
```

如涉及视觉证据：

```text
[视觉证据：<title>, document_id=<id>, asset=<asset_id>, page=<page>]
```

如果文档 metadata 足够完整，且用户明确要求 APA/IEEE/BibTeX，可以在报告末尾附加“近似参考格式”。但必须说明：

```text
以下参考格式基于本地文档元数据生成，可能缺少作者、出版年份或正式出版信息。
```

不要把没有作者/年份/出版源的本地文件伪装成正式论文引用。

### 阶段 7：保存和展示

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

## Per-Document Annotations

### <文档标题>

- `document_id`: <id>
- 类型：<type>
- 主题：<main_topic>
- 目的/问题：<purpose_or_research_question>
- 方法/框架：<methodology_or_framework>
- 关键发现：
  - ...
- 局限/范围：
  - ...
- 本地证据：
  - [本地证据：..., chunk=..., page=...]

## References / Local Sources

- <title> (`document_id=<id>`)
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
