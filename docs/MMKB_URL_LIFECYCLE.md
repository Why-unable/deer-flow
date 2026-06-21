# MMKB RAG 工具资源 URL 生命周期解析

在 Agent 通过 RAG 工具检索本地知识库时，返回结果通常包含两部分：

- `chunks` / `caption_or_ocr`：真正用于回答问题的知识库内容；
- `document_url` / `image_url` / `video_url`：用于让用户打开来源页面或查看相关媒体的链接。

链接通常随检索结果一起出现，但它不是“检索命中的资料本身”。文本证据、来源页面、
文档媒体和 DeerFlow 生成文件分别使用不同的访问方式。

## 链接分类与初始形态

| 类型 | 初始形态 | 最终用途 |
|---|---|---|
| 来源文档页面 | `/documents/<document_id>` | 打开 MMKB 文档页面，仍需浏览器登录和 workspace 权限 |
| 文档图片 | `/api/documents/<document_id>/media/<relative_path>` | 转成 MMKB 限时签名媒体链接后嵌入正文 |
| 文档视频/缩略图 | `/api/documents/<document_id>/media/<relative_path>` | 转成 MMKB 限时签名媒体链接后嵌入正文 |
| MMKB 服务端路径元数据 | `documents/...`、`/home/.../storage/...` | 仅供服务端定位或排查，不应出现在用户正文 |
| DeerFlow 生成文件 | `/mnt/user-data/outputs/<filename>` | 由 MMKB Agent adapter 转成 artifact 下载链接；不属于 RAG 工具阶段 3/4 |

以下五阶段仅描述 **Agent mode 调用 DeerFlow `rag_*` 工具** 时的链接链路。
MMKB 自身的 `rag` mode 不经过阶段 2 和阶段 4，而是在最终回答 prompt 中直接调用
`sign_document_media_url()`。

## 阶段 1：请求透传与 Base URL 捕获 (起源)
此阶段的核心目标是捕获前端真实的访问地址，并将其传入 Agent 的运行上下文中。

*   文件：`mmkb/app/views.py`
    *   **第 1600 行**：在 `openai_chat_completions` 等视图函数中，调用 `request.build_absolute_uri("/")` 获取来源前端的真实 Host。
*   文件：`mmkb/app/services/chat_completion.py`
    *   **第 323 行**：大模型聊天补全服务的代理层，将获取到的 `public_base_url` 塞入发送给 DeerFlow 的上下文 (`context["public_base_url"]`) 中。

## 阶段 2：Agent 发起检索与请求头注水 (发起)
此阶段是 Agent 实际使用 RAG 工具发起请求时，将捕获到的 Base URL 放入请求头发送回 MMKB。

*   文件：`deer-flow/backend/packages/harness/deerflow/tools/custom/rag/context.py`
    *   `resolve_mmkb_runtime_context` 从运行时 `configurable/context` 中提取
        `mmkb_bearer_token` 和 `public_base_url`，并与工具静态 `base_url/timeout`
        合并为请求上下文。
*   文件：`deer-flow/backend/packages/harness/deerflow/tools/custom/rag/client.py`
    *   `HTTPMMKBClient` 把 `search`、`get_document_assets` 等语义操作映射为 MMKB
        HTTP endpoint，并发送 `Authorization` 与 `X-MMKB-Public-Base-URL`。
*   文件：`deer-flow/backend/packages/harness/deerflow/tools/custom/rag/service.py`
    *   `MMKBService` 位于工具与传输之间，使工具不直接依赖 HTTP path；未来 MCP
        client 可实现同一语义接口并复用后续链接与资产策略。

## 阶段 3：MMKB 内部响应重写与完整性签名 (核心变化)
这是最关键的签名阶段，MMKB 接收工具的查询请求并改写带签名的 URL。Django
signing 是带时间戳的完整性签名，不是对 payload 内容加密。

*   文件：`mmkb/app/views.py`
    *   **第 1510 行**：支持 Agent 媒体签名的查询接口通过 `_sign_agent_media_payload` 提取前一步发送过来的 `request.headers.get("X-MMKB-Public-Base-URL")`。
*   文件：`mmkb/app/services/document_media.py`
    *   **第 71 行**：`sign_document_media_urls` 递归扫描响应的字典/列表，找到 `image_url` 等受保护内部路径。
    *   **第 50 行**：调用 `sign_document_media_url` 使用 `DOCUMENT_MEDIA_SIGNING_SALT`，把原始路径签名并拼装，最终转换成形如 `http://<host>/api/document-media/<signed_token>` 的限时公开链接。

当前代码中 `api_search` 和 `rag_get_document_assets` 对应的
`list_document_assets` 都会执行该签名步骤。阶段 4 的
`protected_media_remaining` 日志指标应保持为 0；非 0 表示 MMKB 响应中出现了新的漏签媒体回归。

## 阶段 4：工具接收与绝对路径补全 (防错保底)
DeerFlow 收到 MMKB 响应后，将仍需呈现给用户的相对地址补全为绝对地址。

*   文件：`deer-flow/backend/packages/harness/deerflow/tools/custom/rag/mmkb_links.py`
    *   `process_mmkb_response_links` 统一处理 JSON 响应链接。
    *   只要发现字段名以 `_url`、`_path`、`_base` 结尾且值以 `/` 开头，就会将其与传入的 Base URL 拼接。
    *   该阶段负责地址格式转换，不负责签名，也不能把漏签媒体变成匿名可访问媒体。
    *   `log_mmkb_link_processing` 每次工具调用输出一条不包含 URL 内容的聚合日志。
*   文件：`deer-flow/backend/packages/harness/deerflow/tools/custom/rag/service.py`
    *   `MMKBService` 在任意 transport 返回数据后统一调用上述处理与日志逻辑。
*   文件：`deer-flow/backend/packages/harness/deerflow/utils/mmkb_resource_validation.py`
    *   对工具响应中的 `/api/document-media/<token>` 执行结构校验，检查 payload、
        timestamp、signature 三段是否齐全以及 Base64/字符格式是否合法。
    *   同时统计仍然受保护的 `/api/documents/<id>/media/...` 地址。
    *   同时统计普通 `/documents/<uuid>` 文档页，检查 UUID 路径和源站是否与本次
        run 的 `public_base_url` 一致。文档页仍需浏览器登录和匹配的当前 workspace；
        `document_pages_require_session` 是提示性指标，不计为失败。
    *   DeerFlow 没有 MMKB 签名密钥，因此这里只能发现截断、格式损坏和漏签，不能验证
        密码学签名是否正确或链接是否过期。

日志示例：

```text
mmkb_link_stage4 tool=rag_search triggered=true url_fields=8 relative_fields=2 absolutized_fields=2 trigger_ratio=0.2500 protected_media_remaining=0 signed_media_fields=3
mmkb_tool_resource_validation tool=rag_search thread_id=<thread> run_id=<run> resource_urls=4 signed_media_urls=3 structurally_valid_signed=3 malformed_signed=0 protected_unsigned=0 missing_token_segments=0 invalid_payload_encoding=0 invalid_timestamp=0 invalid_signature=0 document_page_urls=1 structurally_valid_document_pages=1 malformed_document_pages=0 document_origin_matches=1 unexpected_document_origins=0 relative_document_pages=0 document_pages_require_session=1
```

`protected_media_remaining > 0` 表示响应仍含
`/api/documents/<id>/media/...`，聊天前端不携带 bearer 时可能返回 401。
`unexpected_document_origins > 0` 表示文档页没有指向本次请求的公开源站；
若该值为 0 但页面仍返回 404，应优先检查浏览器当前 workspace 是否与 Agent bearer
使用的 workspace 一致。

### 视觉资产工具的两阶段输出

阶段 4 完成后，`assets.py` 会把 `rag_get_document_assets` 的 MMKB 全量资产响应投影为有界
分页目录：默认每页 8 项、最多 10 项，仅保留定位字段、完整签名 URL 和最多
160 字的 OCR/caption 摘要。这样目录不会因体积过大被工具输出预算外置，模型也
不会只看到头尾而猜测中间资产的 URL。

当 Agent 选中准备分析或展示的资产时，必须调用
`rag_get_document_asset(document_id, asset_id)`。该工具先返回独立
`media_urls` 清单，再返回单项完整 OCR、metadata 和诊断字段；即使详情过大被
外置，完整签名 URL 仍位于模型可见的响应头部。

### Preview 不承载可展示图片链接

`rag_get_document_preview` 只用于读取合并 Markdown 的文字上下文。DeerFlow 会在工具
返回前移除 preview 中的原始 Markdown 图片引用、`md_images/...` 相对路径、
受保护的 `/api/documents/<id>/media/...` 媒体路径和 `IMG_META` 注释，并返回
`preview_image_links_removed` / `preview_image_metadata_removed` 计数。

这样做是为了避免模型从 preview Markdown 里复制或拼接不可访问图片路径。需要展示图片
或读取完整 OCR/caption 时，Agent 必须使用 `rag_get_document_assets` 或
`rag_get_document_asset`，并逐字复制返回的 `image_url`。

## 阶段 5：大模型回复生成与链接优先输出 (输出)
最后阶段依靠预置提示词引导大模型优先使用工具返回的 `document_url`、`image_url`
等现成 URL，并逐字保留这些 URL，避免权限损坏和死链。

*   文件：`deer-flow/.deer-flow/agents/research-analyst/SOUL.md` 
    *   要求面向用户的本地文档链接优先使用工具返回的 `document_url`，来源引用优先写成 `[文档标题](document_url)`。
*   文件：`deer-flow/skills/custom/local-deep-research/SKILL.md`
    *   要求中间文件和 subagent 结构化结果保留 `document_id`、标题和 `document_url`，最终本地证据引用优先使用 Markdown 链接。
*   文件：`deer-flow/skills/custom/local-systematic-literature-review/SKILL.md`
    *   要求筛选矩阵、逐文档抽取 JSON、subagent batch 文件和 References / Local Sources 保留并使用 `document_url`。
*   文件：`deer-flow/backend/packages/harness/deerflow/runtime/journal.py`
    *   对 lead agent 最终、无待执行 tool call 的正文再次执行同一资源 URL 结构校验。
    *   当正文包含 MMKB 资源 URL 时，输出 `assistant_resource_validation` 聚合日志，
        并持久化 `assistant.resource.validation` trace event；不会修改或删除正文链接。
    *   通过同一 `thread_id/run_id` 对比工具层和正文层：工具层合法但正文层异常，表示
        模型在最终输出中截断、改写或虚构了链接。

---

完整链路应理解为：

```text
知识库检索命中
-> MMKB 返回文本证据 + 来源/媒体字段
-> MMKB 对图片和视频生成限时签名
-> DeerFlow 对仍为相对地址的字段执行阶段 4 绝对化
-> Agent 根据证据生成回答，并按提示词逐字复制需要展示的链接
-> 链接成为正文 Markdown 的一部分
```

阶段 4 的日志可按 `tool` 聚合：

- 调用级触发比例：`triggered=true` 日志数 / 对应工具日志总数；
- 字段级触发比例：`sum(absolutized_fields) / sum(url_fields)`；
- 漏签风险：`sum(protected_media_remaining)`，预期应为 0。
