# MMKB 视觉资产进入 DeerFlow Sandbox：优化提升方向

## 1. 当前状态

当前 MMKB RAG 工具能够返回视觉资产的 `asset_id`、`image_url`、`caption_or_ocr`、页码和区块信息。DeerFlow 收到的是包含这些字段的文本 `ToolMessage`，图片 URL 主要用于展示或生成 Markdown 图片链接。

当前链路还没有把 MMKB 图片 URL 转换为 DeerFlow 的本地虚拟路径，因此不会自动触发 DeerFlow 原生的图片理解流程。

DeerFlow 已有一条可复用的本地图片链路：

```text
view_image
  → 校验 sandbox 图片路径
  → state 保存轻量路径元数据
  → ViewImageMiddleware 在下一次模型调用前读取文件
  → 生成 Base64 image_url 多模态消息
  → 视觉模型分析
```

对应实现：

- `backend/packages/harness/deerflow/tools/builtins/view_image_tool.py`
- `backend/packages/harness/deerflow/agents/middlewares/view_image_middleware.py`
- `backend/packages/harness/deerflow/tools/tools.py`

## 2. 优化目标

当 Agent 判断某个检索结果需要视觉理解时，将选中的 MMKB Asset 安全地物化到 DeerFlow sandbox，再复用已有 `view_image` 和 `ViewImageMiddleware`，使模型真正获得图片像素，而不是只看到图片 URL、OCR 或 Caption。

## 3. 推荐链路

```text
rag_search
  → 发现相关 Asset
  → rag_get_document_asset（确认 asset_id 和签名 URL）
  → DeerFlow 按需下载到 /mnt/user-data/workspace/...
  → 返回虚拟 image_path
  → Agent 调用 view_image
  → ViewImageMiddleware 注入多模态图片消息
  → 支持视觉的模型分析图片
```

建议增加 DeerFlow 侧的 `rag_stage_visual_asset`（名称可调整）工具。工具输入应以 `document_id + asset_id` 为主，而不是允许模型直接提交任意 URL：

1. 使用当前 MMKB bearer 和 workspace/user 上下文重新确认 Asset 权限；
2. 从 MMKB 服务获取当前有效的签名媒体 URL；
3. 仅允许下载配置的 MMKB 域名，设置连接/读取超时；
4. 校验响应 MIME、文件扩展名、魔数和大小；
5. 写入当前 run 的 sandbox 临时目录并返回 `/mnt/user-data/...` 虚拟路径；
6. 后续由 Agent 调用现有 `view_image`，避免重复实现图片注入逻辑。

第一阶段建议保持“下载”和“查看”两个工具调用，以便复用 DeerFlow 现有权限、审计和视觉中间件；如果后续确认额外一步造成明显延迟，再考虑提供组合工具。

## 4. 为什么采用按需下载

- `rag_search` 可能返回多个图片，提前全量下载会浪费带宽、磁盘和模型调用成本；
- 只有 Agent 判断需要读取图像内容时，才值得产生视觉输入；
- 按 Asset 去重可以避免同一图片在多轮检索中重复下载；
- 下载后立即调用 `view_image`，签名 URL 过期窗口更短；
- Base64 仍由 `ViewImageMiddleware` 在模型调用前临时生成，不写入 checkpoint。

## 5. 模型能力与降级策略

`view_image` 目前只在模型声明 `supports_vision=True` 时加入工具列表。新的视觉资产加载工具应遵循同一能力门控：

- 视觉模型：允许下载并调用 `view_image`；
- 纯文本模型：不进入图片注入链路，使用 OCR、Caption、关联 Chunk 或 MMKB 侧 VQA 结果；
- 没有可用视觉模型时：返回明确的“只能依据文字识别结果回答”状态，不应因向纯文本模型发送 `image_url` 而让整个 Agent 任务失败。

当前 MMKB 自身的 Agentic RAG 已有 Asset VQA，但 DeerFlow 的 `rag_search` 工具不会自动调用它。未来可以二选一：

1. DeerFlow 下载到 sandbox，继续使用 DeerFlow 的视觉模型链路；
2. DeerFlow 调用 MMKB 的 VQA 接口，只把视觉分析文本作为证据返回。

## 6. 安全、可靠性与资源控制

- 不允许模型直接控制任意下载 URL，必须通过 `document_id + asset_id` 解析；
- 下载请求使用 MMKB 允许的内部地址或签名地址，并保留租户、workspace 和用户隔离；
- 限制单文件大小、总下载大小、连接超时、读取超时和响应 MIME；
- 下载文件保存到 run/thread 隔离目录，设置 TTL，在任务结束或后台清理时删除；
- 日志只记录 Asset 数量、状态和耗时，不记录 bearer、签名 token、完整 URL 或私有路径；
- 对 401、403、404、签名过期、超时、格式错误和超大文件返回结构化 ToolMessage 错误；
- 对同一 `(document_id, asset_id, revision)` 做任务内缓存，避免重复下载；
- 继续由 `view_image` 做路径白名单、魔数和大小校验，形成下载前后双重防护。

相关现有约束见：

- `backend/packages/harness/deerflow/tools/custom/rag/tools.py`
- `backend/packages/harness/deerflow/tools/builtins/view_image_tool.py`
- `backend/packages/harness/deerflow/agents/middlewares/view_image_middleware.py`
- `docs/MMKB_URL_LIFECYCLE.md`

## 7. 验收标准

实现后至少应验证：

1. `rag_search` 直接命中的 Asset 可以下载、查看并被视觉模型分析；
2. Chunk 关联图片可以通过 `asset_id` 继续读取；
3. 同一 Asset 重复调用不会重复下载；
4. 纯文本模型不会调用视觉工具，也不会因图片输入格式导致任务失败；
5. 失效签名、越权 Asset、非图片文件和超大文件均被拒绝；
6. 图片 Base64 不进入 checkpoint、持久化消息或普通日志；
7. 下载耗时、失败原因、缓存命中和清理结果具备可观测指标；
8. API、工具、权限、模型能力和清理逻辑均有回归测试。

该方案完成后，项目才可以严谨地描述为“DeerFlow Agent 能对 MMKB 检索出的图片进行视觉分析”；在此之前，更准确的表述是“DeerFlow 能检索并展示 MMKB 图片资产，并使用 OCR/Caption 等文字证据”。
