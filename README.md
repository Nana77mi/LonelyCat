# LonelyCat

“A lonely little cat lives in your computer. It doesn’t want to wreck the house—just wants to play with you.”

## Architecture

- **Python core**: FastAPI service (`apps/core-api`) and background worker (`apps/agent-worker`) for orchestration.
- **Node connectors**: integration bridges in `connectors/` (QQ OneBot v11, future WeChat).
- **Web console**: React/Vite UI shell in `apps/web-console`.
- **Shared packages**: protocol schemas, runtime, memory, KB, skills, MCP in `packages/`.

## Quickstart

```bash
make setup
```

Run all tests:

```bash
make test
```

Or run tests via pnpm + pytest:

```bash
pnpm test
python -m pytest
```

Run dev servers (examples):

```bash
# Core API
python -m uvicorn app.main:app --app-dir apps/core-api --reload

# Web console
pnpm --filter @lonelycat/web-console dev
```

### Agent Worker LLM examples

```bash
LLM_PROVIDER=stub python -m agent_worker.chat "hi"
LLM_PROVIDER=openai OPENAI_API_KEY=... python -m agent_worker.chat "hi"
LLM_PROVIDER=qwen QWEN_API_KEY=... python -m agent_worker.chat "hi"
LLM_PROVIDER=ollama OLLAMA_BASE_URL=... python -m agent_worker.chat "hi"
```

## Security Note

LonelyCat defaults to **least privilege** access, sandboxed workspaces in `data/workspaces`, and audit-friendly design. Any tool execution or connector should enforce explicit allowlists and produce audit logs.

## 部署方案（Production/自建）

以下方案基于当前仓库结构，覆盖依赖准备、数据库/缓存、后端服务、前端控制台与日常运维。

### 1. 依赖与环境准备

- **Python 3.11+**（后端 API 与 Worker）
- **Node.js 18+ + pnpm**（Web Console）
- **Docker + Docker Compose**（Postgres/Redis）

### 2. 获取代码并安装依赖

```bash
git clone <your-repo-url>
cd LonelyCat

# Python + Node 依赖
make setup
```

### 3. 启动基础依赖（Postgres/Redis）

仓库已提供 `deployments/docker-compose.yml`，用于启动数据库与缓存：

```bash
docker compose -f deployments/docker-compose.yml up -d postgres redis
```

> 默认数据库账户：`lonelycat/lonelycat`，数据库名：`lonelycat`。如需调整，请修改 `deployments/docker-compose.yml`。

### 4. 启动后端服务（Core API + Agent Worker）

建议在宿主机使用虚拟环境或系统服务方式启动：

```bash
# Core API（生产场景建议使用 gunicorn/uvicorn workers）
python -m uvicorn app.main:app --app-dir apps/core-api --host 0.0.0.0 --port 8000

# Agent Worker
python -m worker.main --app-dir apps/agent-worker
```

> 若希望全部通过 Docker Compose 托管，请在 `deployments/docker-compose.yml` 中为 `core-api` 与 `agent-worker` 增加依赖安装步骤（例如在镜像中执行 `pip install -e ...` 或使用自定义 Dockerfile 构建应用镜像）。

### 5. 构建与部署 Web Console

```bash
pnpm --filter @lonelycat/web-console build
```

构建产物位于 `apps/web-console/dist`，可用任意静态资源服务器部署（Nginx/Apache/云对象存储均可）。

### 6. 反向代理与访问入口（可选）

推荐通过 Nginx 统一入口：

- `/api` 代理到 Core API（`http://127.0.0.1:8000`）
- `/` 指向 Web Console 静态资源目录

### 7. 运维建议

- **日志**：Core API / Worker 输出到标准输出，建议由 systemd 或容器运行时接管。
- **数据**：业务数据由 Postgres/Redis 承载；工作区位于 `data/workspaces`。
- **升级**：拉取新代码后重启服务，必要时执行依赖更新（`make setup`）。
