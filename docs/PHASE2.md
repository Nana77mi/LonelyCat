# Phase 2 总目标与子项

- **工具 provider 可插拔**：builtin / MCP / sandbox / browser / doc / …
- **能力分级**：L0 只读、L1 写文件、L2 执行/网络/CLI（强隔离）
- **人在回路**：副作用工具默认需确认（复用 edit_docs 二阶段模式）
- **可观测**：每次工具调用落 step、带输入输出 preview、带 trace_id、可回放

---

## 2.1 ToolRuntime v1：Provider 架构 + 工具选择策略（不引入 MCP）

### 做什么

- ToolCatalog 扩成多 provider 聚合：
  - **ToolMeta** 增加：`provider_id`、`capability_level`（L0/L1/L2）、`requires_confirm`（bool）、`timeout_ms`
  - **ToolProvider** 接口：`list_tools() -> [ToolMeta]`、`invoke(tool_name, args, ctx) -> result`
  - **builtin_provider**、**stub_provider**（先不加 MCP）
- 工具选择/冲突规则：
  - `preferred_provider_order = ["builtin", "stub"]`（可配置）
  - 或按 risk_level/capability_level 自动选更安全实现

### 验收

- [x] research_report 仍然能跑
- [x] 切换 provider 顺序（配置）能改变工具实现来源
- [x] steps/meta 仍然清晰（含 provider_id、capability_level）

### 实现状态

- **已完成**：`ToolMeta` 扩展、`ToolProvider` 协议、`BuiltinProvider`/`StubProvider`、`ToolCatalog` 多 provider 聚合与 `preferred_provider_order`、`ToolRuntime` 通过 catalog 调用 provider；测试 `test_preferred_provider_order_changes_tool_source`。

---

## 2.2 MCP 接入 v0：把 MCP 当成一个 Provider

- 新增 **MCPProvider**；先支持 **client 注入**（测试/适配用），stdio MCP 待 v0.1
- 将 MCP server 的 tools 映射成 ToolMeta（name 强制前缀 `mcp.<server>.<tool_name>`）
- invoke 时 args 透传 MCP，拿 ToolResult 归一为 dict
- 安全边界：MCP tools 默认 `risk_level="unknown"`、`capability_level=L0`；`side_effects=True` 的默认 `requires_confirm=True`
- v0 约束：① worker shutdown 时 `ToolCatalog.close_providers()`（atexit 已挂到 default catalog）② 命名空间前缀 ③ list_tools 失败时 provider 仍注册、tools 为空、`mcp.list_tools.failed` 打日志 ④ **close 后 invoke 抛 `MCPProviderClosedError(code=ProviderClosed)`**；测试 close 后 invoke 失败且 error.code 稳定

### 验收

- [x] 能注册并列出 MCP tools（client 注入时；UI Tools 面板可选）
- [x] 能调用一个 L0 MCP tool 并在 steps 里看到 tool.\<name\> + preview（通过现有 ToolRuntime）
- [x] ToolNotFound / list_tools 失败可降级；close 可多次调用；**close 后 invoke 必须失败且 error.code=ProviderClosed**
- [x] stdio 真实 MCP server 接入（v0.1）

---

### 2.2 四阶段（从假到真、从单到多、从无治理到治理）

- **v0**（已完成）：client 注入 + 前缀 + 降级 + close + closed 后 invoke 抛 ProviderClosed
- **v0.1**（已完成）：stdio 真 MCP（单 server、最小闭环）
  - 手写最小 JSON-RPC over stdio（一行一 JSON + request_id），零 PyPI mcp 依赖；MCPStdioClient 同步外观 + 后台读线程；MCPProvider 保持纯同步；list_tools 一律降级不抛，invoke 才抛 Timeout/ConnectionError
  - 配置：MCP_SERVER_NAME、MCP_SERVER_CMD、MCP_SERVER_ARGS_JSON（优先）或 MCP_SERVER_ARGS（shlex.split）、MCP_SERVER_CWD、MCP_TIMEOUT_MS；get_default_catalog() 读 env 自动注册 MCPProvider；能调用 mcp.srv.ping 且 step 有 name/preview；atexit close 杀子进程
  - 三条防线：① spawn 失败 → list_tools 降级为空 + 日志 `mcp.spawn.failed` ② 仅 invoke 超时 → MCPTimeoutError(code=Timeout) 落 step；list_tools 超时也降级为空 ③ close() → 先停 reader 再 terminate → 等待 → kill fallback，幂等
- **v0.2**（已完成）：多 MCP server（无 UI 配置）
  - 配置如 `MCP_SERVERS_JSON='[{"name":"srv1","cmd":["python","..."],"cwd":null}, ...]'`；每个 server 一个 provider_id=mcp_\<name\>，tool 前缀 mcp.\<name\>.\<tool\>
  - 当 `MCP_SERVERS_JSON` 已设置时优先于单 server 环境变量（`MCP_SERVER_CMD` 等）；未设置或无效 JSON 时回退单 server 逻辑
  - 验收：Catalog.list_tools 含多 server 工具；preferred_provider_order 可调
  - 实现：`_mcp_servers_from_env()` 解析 JSON；`_default_catalog_factory()` 多 server 时逐个注册 MCPProvider 并设置 order = builtin + mcp_* + stub；测试 `test_catalog_list_tools_multiple_mcp_servers`、`test_mcp_servers_from_env_parsing`、`test_default_catalog_factory_with_mcp_servers_json_registers_multiple_servers`
  - **加固**：① 非法 JSON 时打 warning（含截断 raw，避免静默回退单 server）② server name 仅允许 `[a-z0-9_]+`，非法/重复 name 跳过并 warning，去重保留第一个 ③ cmd 非空校验，坏项跳过并 warning，其余 server 仍返回；测试 `test_mcp_servers_from_env_invalid_json_logs_warning`、`test_mcp_servers_from_env_invalid_name_filters`、`test_mcp_servers_from_env_duplicate_name_keeps_first_and_warns`、`test_mcp_servers_from_env_empty_cmd_skips_item_and_warns`
- **2.3 vs 2.4**：推荐先 **2.4 Web 真实化**（research_report 立刻真能用、可演示、L0 风险小）；若目标为「开发者/自动化能力」则先 2.3 Sandbox（run_code_snippet 强 demo、L2）
- **2.5 Skills**：建议在 2.4 或 2.3 **任一落地后**再开；至少具备真实 web 或 sandbox.exec 后再做能力包治理

---

## 2.3 Sandbox v0：L2 执行环境

### 2.3a 本地隔离 v0

- 提供 **sandbox.exec**：白名单命令（python -c, node -e）
- 工作目录固定（如 `./sandbox_workspace/{conversation_id}`）、超时/内存/输出截断、路径白名单

### 2.3b 容器化 v1

- Docker/gVisor 跑 sandbox worker；core-api/agent-worker 通过 RPC 调用；输出作为 artifacts

### 验收

- [ ] 新增任务 **run_code_snippet**（L2）：input language+code → steps write_files → sandbox.exec → collect_outputs；artifacts stdout/stderr/files；失败可回放

---

## 2.4 Browser / Web 真实化

- **web.search**：接稳定 provider（Serper/Brave/Bing/自建）
- **web.fetch**：robots/timeout/size limit、HTML 提取（readability）
- **web.extract**：正文抽取 + 去噪
- artifacts.evidence：引用片段 + source_index（已有）

### web.search ToolResult 合同（canonical 形状）

- **规范返回**：`{"items": [...]}`，每项 `{ "title": str, "url": str, "snippet": str, "provider": str }`；url 须为 http(s)；title/snippet 可空串。
- **list 形状**：仅作历史兼容，所有提供 web.search 的 provider（WebProvider、BuiltinProvider、StubProvider）已统一为 dict 形状；**后续会逐步淘汰 list**，调用方应只依赖 `result["items"]`。
- **默认 backend**：未设置 `WEB_SEARCH_BACKEND` 时使用 stub，避免 CI/离线环境 flake；用户想启用真实搜索可设置 `WEB_SEARCH_BACKEND=ddg_html` 或 `searxng`（自备实例）。
- **Backend matrix**：stub（默认/离线）、ddg_html（免费真实，可能 blocked）、searxng（免费但需自备服务）、brave（需 key，稳定，可选 2.4.3）；未知值打 warning 回退 stub。项目默认不要求 Docker、不要求任何额外 key；高级用户 opt-in。
- 见 `docs/spec/tools-web-search.md`。

### 验收

- [ ] research_report 输入 query，返回真实来源的 report + sources；max_sources 控制；fetch 有输出大小限制与告警

---

## 2.5 Skills 体系

- **Skill**：工具组合 + 约束 + 模板（如 research_report、edit_docs）
- **Task**：带状态/steps/artifacts 的执行实例（Run）
- skills/ 目录：skill manifests（YAML/JSON）：skill_name、required_tools、allowed_run_types、risk_policy
- AgentLoop 按已加载 skills 决定“允许做什么”
- **建议**：在 2.4 或 2.3 任一落地后再开始；至少具备真实 web 或 sandbox.exec 后再做能力包治理

### 验收

- [ ] 新增/删除 skill manifest 后，启动时加载/卸载
- [ ] UI 可选显示当前启用的 skills
- [ ] 禁用某 skill 后，相关任务 type 被拒绝创建
