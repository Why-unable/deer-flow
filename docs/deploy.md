# MMKB 集成版 DeerFlow 部署指南

本文只说明 MMKB 集成版 DeerFlow 的最简 Docker 部署流程。

## 1. 配置环境变量

### Frontend `.env`

从示例文件创建：

```bash
cp frontend/.env.example frontend/.env
```

默认配置通常可以直接使用。如需修改前端访问地址，再编辑
`frontend/.env`。

### DeerFlow 根目录 `.env`

从示例文件创建：

```bash
cp .env.example .env
```

根据当前模型和工具配置填写所需变量。DeerFlow 根目录 `.env` 的内容可尽量
与 MMKB 根目录 `.env` 保持一致，尤其是两边共同使用的模型或服务密钥。

MMKB 与 DeerFlow 会分别加载各自的 `.env`，不会自动读取对方的文件。

其中最关键的是：

```dotenv
DEER_FLOW_INTERNAL_AUTH_TOKEN=<shared-secret>
```

MMKB 与 DeerFlow 根目录 `.env` 中的 `DEER_FLOW_INTERNAL_AUTH_TOKEN`
**必须完全一致**。如果缺失、不一致，或者服务进程没有重新加载修改后的
环境变量，MMKB 的 agent 模式可能返回 `HTTP 401 not_authenticated`。

不要将包含真实密钥的 `.env` 提交到 Git。

## 2. 检查内部认证

从 DeerFlow 根目录运行：

```bash
./scripts/check_deerflow_internal_auth.sh
```

脚本必须检查通过后再继续部署。

如果一边或两边缺少 `DEER_FLOW_INTERNAL_AUTH_TOKEN`，可以尝试：

```bash
./scripts/check_deerflow_internal_auth.sh --fix
```

修复后重新运行检查脚本，确认结果通过。已经运行且加载了正确 token 的 MMKB
无需重启；脚本会根据实际运行状态给出启动或重启提示。

## 3. Docker 部署

从 DeerFlow 根目录依次运行：

```bash
make docker-init
make docker-start
```

启动完成后，DeerFlow 默认统一入口为：

```text
http://127.0.0.1:2026
```

## 4. 更详细的文档

DeerFlow 侧的 MMKB 集成改动、实现目的和维护注意事项见：

- [MMKB_INTEGRATION_CHANGES.md](MMKB_INTEGRATION_CHANGES.md)

MMKB 侧的完整部署、集成架构和 Agent 适配器说明见 MMKB 仓库的 `docs/`
目录，重点包括：

- `docs/DEERFLOW_DEPLOYMENT_STATUS.md`
- `docs/DEERFLOW_INTEGRATION.md`
- `docs/DEERFLOW_AGENT_ADAPTER.md`
