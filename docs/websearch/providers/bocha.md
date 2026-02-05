# Bocha Web Search Provider

Bocha 作为 web.search 的 API 后端，通过 Bocha AI 开放平台的 Web Search API 提供实时搜索能力。需配置 API Key。

## 配置方式

### 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `WEB_SEARCH_BACKEND` | 设为 `bocha` 时启用 Bocha 后端 | `bocha` |
| `BOCHA_API_KEY` | Bocha API Key（必填） | 从 Bocha AI 平台创建 |
| `BOCHA_BASE_URL` | API 基地址（可选） | 默认 `https://api.bochaai.com` |
| `BOCHA_TIMEOUT_MS` | 请求超时毫秒（可选） | 默认 15000 |
| `BOCHA_TOP_K_DEFAULT` | 默认返回条数 1～10（可选） | 默认 5 |

### 设置 API（Web Console / DB）

在「设置」中可选择「Bocha（API Key）」作为搜索后端，并填写：

- **Bocha API Key（必填）**：可填 `$BOCHA_API_KEY` 表示从环境变量读取
- **Bocha Base URL**：默认 `https://api.bochaai.com`
- **Bocha 超时 (ms)**：优先于全局 Web 搜索超时
- **默认返回条数 (top_k)**：1～10

设置会随 run 的 `settings_snapshot` 带到 worker，无需在 worker 环境再配一遍 Key。

## 快速跑通（约 10 分钟）

1. 在 [Bocha AI 开放平台](https://aisharenet.com/bochaai/) 登录并进入「API KEY 管理」创建 API KEY。
2. 本地 `.env` 或 secrets 中设置：
   ```bash
   BOCHA_API_KEY=你的Key
   WEB_SEARCH_BACKEND=bocha
   ```
   或在 Web Console 设置里选择 Bocha 后端并填写 Key（可填 `$BOCHA_API_KEY`）。
3. 创建新任务（如 research_report），新任务会使用当前设置的 Bocha 后端。
4. 查看任务执行结果与日志，确认 `provider=bocha` 与 `items_count` 等。

## 常见报错与排查

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| **401 / 403** | Key 错误、未传或已失效 | 检查 `BOCHA_API_KEY` 或设置中的 API Key 是否正确；确认 Key 未过期、未删除。 |
| **429** | 请求频率超限 | 降低并发或请求频率；稍后重试。日志中会看到 `error_type=WebBlocked`、`status=429`。 |
| **超时 (Timeout)** | 网络或上游慢 | 适当增大 `BOCHA_TIMEOUT_MS` 或设置中的 Bocha 超时；检查网络与代理。 |
| **EmptyResult** | 上游返回 0 条结果 | 正常情况；可换 query 或稍后重试。 |
| **WebParseError**（Missing or invalid results/data array） | 响应中未找到结果数组 | 错误信息会带 `response keys: [...]`，表示 Bocha 实际返回的顶层字段；可对照 Bocha 文档或联系支持确认结果数组字段名（当前支持 `results`/`data`/`list`/`items` 及嵌套 `data.list` 等）。 |
| **WebParseError**（其他） | 响应结构异常或缺字段 | 可抓日志中的 request_id 或 response_keys 联系 Bocha 支持排查。 |

日志中会包含 `provider=bocha`、`latency_ms`、`items_count`、`error_type`（若失败）以及 Bocha 返回的 `request_id`（若有），便于定位是 Key 错、限流、超时还是解析失败。

## API 形态（Bing 兼容）

- **端点**：`POST {base_url}/v1/web-search`
- **鉴权**：Header `Authorization: Bearer {BOCHA_API_KEY}`
- **请求体**：`{ "query": "...", "count": 5 }`（可选 `freshness`、`summary` 等）
- **响应**：Bing Search API 兼容结构。网页结果在 **`webPages.value`**（官方主路径）；部分网关可能包一层 `data`，即 `data.webPages.value`。兼容旧形态 `results` / `citations`。
- **每条 item**：`name`（标题）、`url`、`snippet` 或 `summary`、可选 `datePublished`、`siteName`、`siteIcon`（后两者进 item.meta）。

解析优先级：`payload.webPages.value` → `payload.data.webPages.value` → `payload.results` → `payload.citations`。

实现见 `apps/agent-worker/worker/tools/web_backends/bocha.py`；单测见 `apps/agent-worker/tests/test_bocha_backend.py`。
