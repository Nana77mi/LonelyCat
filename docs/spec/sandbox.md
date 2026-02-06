# Sandbox 沙箱规范

本规范定义 core-api 内沙箱执行（Docker CLI + Path Adapter）的目录结构、API、Policy 合并、Exec 审计与 Skills manifest 约定。

---

## 1. 架构与关键决策

- **SandboxRunner 在 core-api**：worker 只发 `POST /sandbox/execs` 请求；core-api 负责 policy 校验、创建目录、启动容器、收集 artifacts、写审计记录。
- **跨平台**：统一依赖 Docker Engine（Windows Docker Desktop / WSL2）；Path Adapter 解决 Win/WSL 路径双栈；网络 Phase 1 固定 `none`。
- **Policy 合并**：`系统默认 ← Settings snapshot ← Skill manifest ← 请求 overrides`，core-api 校验禁止越权。
- **执行入口**：Docker **CLI**（非 SDK），便于 Windows/WSL 行为一致。

---

## 2. Workspace 目录与 project_id

- **根路径**：由 Settings 的 `sandbox.workspace_root_win` / `sandbox.workspace_root_wsl` 决定。
- **project_id 规则**：若无 project 概念，先用 **conversation_id 作为 project_id**（后续可迁移）。

```
workspace/
  projects/
    <project_id>/
      inputs/           # 只读，core-api 写入
      work/              # 可写工作区
      artifacts/
        <exec_id>/       # 每次执行单独目录
          stdout.txt
          stderr.txt
          manifest.json  # 产物清单 hash/size/path
          meta.json      # 执行元信息 policy_snapshot、exit_code 等
```

- **安全边界**：挂载源目录**只能是** `workspace/projects/<project_id>/{inputs,work,artifacts}` 这三个固定模板路径；禁止 workspace 外、repo 根或同层目录挂载。

---

## 3. Path Adapter（Win/WSL）

- 输入：当前运行环境（auto/windows/wsl）、Settings 中的 `workspace_root_win` / `workspace_root_wsl`。
- 输出：`host_path_native`（当前系统可读写）、`docker_mount_path`（传给 `docker run -v`）。
- Windows 上不传 `/mnt/d/...`，WSL 上不传 `D:\...`；可选用 `wslpath` 做缺失项转换并报错提示。

---

## 4. Docker 沙箱运行规范（Phase 1）

- `--network=none`，`--cap-drop=ALL`，`--security-opt=no-new-privileges`
- `--pids-limit` / `--memory` / `--cpus` 来自 policy
- `--user=1000:1000`，`--workdir=/workspace/work`
- 挂载：`inputs → /workspace/inputs:ro`，`work → /workspace/work:rw`，`artifacts/<exec_id> → /workspace/artifacts:rw`
- Phase 1 不强制 rootfs `--read-only`
- 镜像：`python:3.12-slim` 为基础，安装 bash/coreutils/findutils/jq/git（可选），创建用户 sandbox uid 1000

---

## 5. API（core-api）

- **POST /sandbox/execs**：请求体 project_id, skill_id, exec (kind, command, args, cwd, env), inputs[], policy_overrides, task_ref；返回 exec_id, status, exit_code, artifacts_dir, stdout_path, stderr_path。
- **GET /sandbox/execs**：列表，支持 `?task_id=...`。
- **GET /sandbox/execs/{exec_id}**：单条详情。
- **GET /sandbox/execs/{exec_id}/artifacts**：列出产物文件。
- **GET /sandbox/health**（PR2.5）：runtime_mode、workspace_root_native、docker_cli_path、docker version、docker context、可写检查。

### 5.1 落地细节

| 项目 | 规则 |
|------|------|
| exec.kind 与 command | Phase 1：`kind=shell` → `command=bash`，args 形如 `["-lc", "<script>"]`；`kind=python` → `command=python`，args 形如 `["-c", "<code>"]` 或 `["/workspace/inputs/main.py"]`。 |
| inputs[] 写入 | `inputs[].path` 只允许相对 `inputs/` 的路径；写入前 **normpath 校验**，拒绝 `../`，返回 400。 |
| stdout/stderr 截断 | 超限时截断写文件，不杀进程；写 `stdout_truncated` / `stderr_truncated=true`。 |
| artifacts 总量 | 只统计 `artifacts/<exec_id>/` 下文件；`work/` 不纳入上限。 |
| 并发控制 | Settings 中 `sandbox.max_concurrent_execs`（默认 2 或 4），semaphore 限制。 |

### 5.2 Policy 默认（系统级）

- net.mode=none，timeout_ms=60s，max_stdout_bytes/max_stderr_bytes=1MB，max_artifacts_bytes_total=50MB，memory_mb=1024，cpu_cores=1，pids=256。

---

## 6. Exec Record（审计）

- **DB 表 sandbox_execs**：exec_id, project_id, task_id, conversation_id, skill_id, image, cmd, args, cwd, env_keys（不存敏感值）, policy_snapshot, status, exit_code, error_reason, started_at, ended_at, duration_ms, artifacts_path, stdout_truncated, stderr_truncated。
- **artifacts 目录**：同次执行写 `meta.json`（含 docker_mounts 便于定位）；与 DB 可对齐。

---

## 7. Skills 标准（manifest）

- **目录（repo 根）**：`skills/<skill_id>/manifest.json`，`skills/_schema/manifest.schema.json`。目录名必须等于 `id`（含点，如 `shell.run`）。
- **字段五组**：Identity（schema_version, id, name, description）、Interface（interface.inputs, interface.outputs）、Runtime（runtime.kind=docker, image, entrypoint）、Security（permissions.fs, permissions.net）、Limits（limits.*）。
- **manifest.schema.json 约束**：
  - `id` 必须匹配 `[a-z0-9]+(\.[a-z0-9]+)+`（如 shell.run）。
  - `runtime.kind` 必须是 `docker`。
  - `permissions.net.mode` Phase 1 只能是 `none`。
  - `permissions.fs.read` / `permissions.fs.write` 只能在 `inputs/**`、`work/**`、`artifacts/**` 三类前缀下。
- **调用**：PR4 提供 POST /skills/{id}/invoke 作为上层入口；MCP：list_tools ← GET /skills，call_tool ← POST /skills/{id}/invoke。PR5：agent-worker 内 SkillsProvider 将 GET /skills 映射为 list_tools、POST /skills/{id}/invoke 映射为 invoke，工具名为 skill.\<id\>（如 skill.shell.run）。
