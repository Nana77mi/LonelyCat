# LonelyCat

“A lonely little cat lives in your computer. It doesn’t want to wreck the house—just wants to play with you.”

## Architecture

- **Python core**: FastAPI service (`apps/core-api`) and background worker (`apps/agent-worker`) for orchestration.
- **Node connectors**: integration bridges in `connectors/` (QQ OneBot v11, future WeChat).
- **Web console**: React/Vite UI shell in `apps/web-console`.
- **Shared packages**: protocol schemas, runtime, memory, KB, skills, MCP in `packages/`.

## Quickstart

### Docker（推荐，Linux / WSL / PowerShell 通用）

仅需安装 [Docker](https://docs.docker.com/get-docker/) 与 Docker Compose（Docker Desktop 已自带）。在纯净环境中：

```bash
git clone <your-repo-url>
cd LonelyCat
docker compose up -d --build
```

首次构建可能稍长；之后只需 `docker compose up -d`。然后：

- **用户界面**: http://localhost:8000
- **API 文档**: http://localhost:5173/docs

数据默认使用 SQLite，持久化在项目下的 `./data` 目录。可选：复制 `.env.example` 为 `.env` 做自定义配置。

### 本机运行（无需 Docker）

**Linux / WSL / macOS**

前置：Python 3.11+、Node.js 18+、pnpm（`corepack enable` 后 `pnpm install`）。WSL/Linux 下 `make` 使用 `.venv-dev`，与 Windows 主环境 `.venv` 分离，避免同一目录下两边冲突。

```bash
make setup
make up
```

**Windows（PowerShell）**

前置：Python 3.11+、Node.js 18+、pnpm（`corepack enable` 后 `corepack prepare pnpm@latest`）。若脚本无法执行，请先运行：

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

首次安装依赖并启动：

```powershell
.\scripts\setup.ps1
.\scripts\up.ps1
```

停止后端与 Worker：`.\scripts\down.ps1`；Web 在前台运行时用 Ctrl+C 停止。

---

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
# Core API (端口 5173)
python -m uvicorn app.main:app --app-dir apps/core-api --reload --port 5173

# Web console (端口 8000, uses /api proxy by default)
# Requests to /api/* are proxied to http://127.0.0.1:<CORE_API_PORT>/* (via Vite dev server)
# CORE_API_PORT defaults to 5173, can be overridden via environment variable
CORE_API_PORT=5173 pnpm --filter @lonelycat/web-console dev --port 8000
```

或者使用一键启动（Linux/WSL/macOS）：

```bash
make up
```

## Demo script (30s)

```bash
# 一键启动所有服务（核心 API + 用户界面）
make up
```

启动后：

1. 打开浏览器访问 `http://localhost:8000` 查看用户界面
2. 点击右上角设置按钮，进入 Memory 管理页面
3. 在另一个终端中，使用 agent worker 创建一个提案：
   ```bash
   python -m agent_worker.chat "Remember that I like matcha."
   ```
4. 回到控制台，查看新的提案并点击 **Accept**
5. 验证已接受的提案现在在 **Facts** 中显示为 `ACTIVE`

> **开发环境设置**: 
> - 用户界面运行在端口 **8000** (`http://localhost:8000`)
> - 核心 API 运行在端口 **5173**（默认，可通过 `CORE_API_PORT` 环境变量修改）
> - 用户界面通过 Vite 代理将 `/api/*` 请求转发到 `http://127.0.0.1:<CORE_API_PORT>/*`
> - 这意味着 `/api/memory/proposals` 会自动变为 `http://127.0.0.1:<CORE_API_PORT>/memory/proposals`
> - 如果 core-api 端口被占用（如 8000），可以设置 `CORE_API_PORT=8001` 来使用其他端口
>
> **生产环境**: 要指向不同的 API 源，请在构建前设置 `VITE_CORE_API_URL`（或 `VITE_API_BASE_URL`）
> （例如：`VITE_CORE_API_URL=http://api.example.com pnpm build`）。默认为 `/api`，适用于反向代理设置。

## Proposal workflow (quick reference)

1. Run the Core API and web console (see above).
2. Trigger a proposal via the agent worker:
   ```bash
   python -m agent_worker.chat "Remember that I like matcha."
   ```
3. In the console **Memory** page:
   - Review the proposal under **Proposals** and click **Accept** or **Reject**.
4. Accepted proposals appear as `ACTIVE` facts; rejected proposals remain in the proposals list with
   status `REJECTED`.

## Memory review workflow

Proposed facts are reviewed before they become active memory records.

1. **Propose a fact**: `POST /memory/facts/propose` creates a proposal with status `PENDING`.
2. **Review proposals**: `GET /memory/proposals` lists pending items.
3. **Accept or reject**:
   - `POST /memory/proposals/{proposal_id}/accept` creates an `ACTIVE` fact record.
   - `POST /memory/proposals/{proposal_id}/reject` stores the rejection reason.
4. **List facts**: `GET /memory/facts` returns active/retracted facts as before.

The web console's Memory page surfaces pending proposals for review and action.

## Auto-accept demo

For demo environments, the Core API can auto-accept proposals based on confidence and predicate filters:

```bash
# Enable auto-accept
MEMORY_AUTO_ACCEPT=1

# Optional confidence threshold (default: 0.85)
MEMORY_AUTO_ACCEPT_MIN_CONF=0.9

# Optional predicate allowlist (comma-separated; empty means allow all)
MEMORY_AUTO_ACCEPT_PREDICATES=likes,uses,plays
```

When enabled, proposals that meet the thresholds are automatically accepted and immediately appear in
`GET /memory/facts`, while still recording an accepted proposal entry.

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

- **快速体验**：根目录 `docker compose up -d --build` 使用 SQLite，无需 Postgres/Redis（见上方 Quickstart）。
- **生产/自建**：需要 Postgres/Redis 时使用 `deployments/docker-compose.yml` 启动数据库与缓存，再在宿主机或镜像中运行 Core API / Worker（见下）。

### 1. 依赖与环境准备

- **Python 3.11+**（后端 API 与 Worker）
- **Node.js 18+ + pnpm**（Web Console）
- **Docker + Docker Compose**（可选，用于 Postgres/Redis 或一键运行）

### 2. 获取代码并安装依赖

```bash
git clone <your-repo-url>
cd LonelyCat

# Python + Node 依赖（Linux/WSL/macOS）
make setup
```

Windows PowerShell：`.\scripts\setup.ps1`

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
