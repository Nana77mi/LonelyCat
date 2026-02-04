# web.search 工具合同

## ToolResult 规范形状（canonical）

**唯一支持的返回形状**：`{"items": [...]}`

- `items`：数组，每项为 `{ "title": string, "url": string, "snippet": string, "provider": string }`
- `url` 必须为 `http://` 或 `https://` 开头，否则 normalize 阶段会丢弃该条
- `title`、`snippet` 可为空串；`provider` 由 backend/provider 填充

所有实现 web.search 的 ToolProvider（WebProvider、BuiltinProvider、StubProvider）均输出此形状。

## 历史兼容

- 返回 **list**（裸数组）的形状仅为历史兼容，**已废弃**，后续会逐步淘汰
- 调用方（如 runner）应只解析 `result.get("items", result)` 并断言 `isinstance(raw_sources, list)`，不应再依赖“可能为 list”的双分支

## 输入

- `query`：string，minLength=1
- `max_results`：integer，1～10（可选，默认由 provider 配置）

## Backend matrix

| 值 | 说明 |
|----|------|
| **stub**（默认） | 离线/CI 稳定，不打网；固定 2～3 条结果 |
| **ddg_html** | 免费真实，DuckDuckGo HTML 解析；无 key、无 Docker；可能被挡 |
| **searxng** | 免费但需自备 SearXNG 实例；配置 `SEARXNG_BASE_URL`（可选 `SEARXNG_API_KEY`）。超时：`SEARXNG_TIMEOUT_MS` 优先，未设置时复用 `WEB_SEARCH_TIMEOUT_MS` |
| **brave** | 需 API key，高稳定；配置 `BRAVE_API_KEY`（可选，后续 2.4.3） |

- **默认**：未设置 `WEB_SEARCH_BACKEND` 时为 **stub**，保证 CI/离线不依赖外网。
- **高级用户**：可按需设置 `WEB_SEARCH_BACKEND=ddg_html` 或 `searxng`（并配置对应 env）；项目默认不要求 Docker、不要求任何额外 key。

## 默认 backend 策略

- **默认 stub**：为避免 CI/离线环境 flake，`WEB_SEARCH_BACKEND` 未设置时使用 stub（不打网）。
- **启用真实搜索**：设置 `WEB_SEARCH_BACKEND=ddg_html` 使用 DuckDuckGo HTML；或 `WEB_SEARCH_BACKEND=searxng` 并设置 `SEARXNG_BASE_URL` 使用自备 SearXNG。
- **未知值**：若 `WEB_SEARCH_BACKEND` 为未知值，记录 warning 并回退 stub。

## 错误码

- `InvalidInput`：query 空、max_results 越界
- `WebProviderError`：backend 异常
- `ToolNotFound`：工具名非 web.search（对 WebProvider 而言）
- `Timeout` / `WebBlocked` / `WebParseError` / `NetworkError`：ddg_html / searxng 等后端专用
- `AuthError`：searxng 401/403 或 brave 缺 key；`BadGateway`：5xx 上游不可用（SearXNG 服务挂了/502 等）

## research_report 与 fetch

research_report 的抓取能力来自 **web.fetch** 工具；fetch 的输入/输出与错误码合同见 [tools-web-fetch.md](tools-web-fetch.md)。
