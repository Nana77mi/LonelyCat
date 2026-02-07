# 方向 3：百度 Warm-up + Cooldown 实现计划（修订版）

## 目标

- **Warm-up**：在 TTL 内仅做一次（或 cookie 为空时）先 GET 百度首页，再用同一 session 请求搜索，复用 cookie。
- **Cooldown**：仅对 **captcha_required** 触发较长 cooldown；**按 (proxy + UA) 做 key**，不同网络配置互不误伤；429 用短 backoff，403 可单独处理。
- **Session**：Backend 持有一个 httpx.Client（延迟创建、实例级复用），提供 close 挂到框架生命周期（若有）。

---

## A. 必做修正点

### A.1 Cooldown 按 key 隔离（proxy + UA）

**问题**：单变量 `_baidu_cooldown_until` 会导致：启用代理后仍被旧 cooldown 阻止；多网络/多配置互相误伤。

**修正**：

- **结构**：`_baidu_cooldown: Dict[str, float]`，key = `f"{proxy_enabled}:{proxy_normalized}:{user_agent_prefix}"`（例如 proxy 归一化、UA 取前 64 字符或 hash，避免 key 过长）。
- **写入**：仅在抛出 `WebBlockedError(detail_code="captcha_required")` 时更新 `_baidu_cooldown[key] = time.time() + cooldown_minutes * 60`。
- **读取**：`search()` 入口用当前实例的 proxy/UA 算 key，若 `time.time() < _baidu_cooldown.get(key, 0)` 则直接抛 `captcha_cooldown`。

**验收**：

- 未走代理触发 captcha → 该 key 的 cooldown 生效。
- 开启代理后（key 变化）可立刻再尝试，不被旧 cooldown 阻止。

**涉及文件**：[apps/agent-worker/worker/tools/web_backends/baidu_html.py](apps/agent-worker/worker/tools/web_backends/baidu_html.py) — 模块级 `_baidu_cooldown: Dict[str, float]`，key 生成函数，入口检查与写入点。

---

### A.2 Cooldown 只对 captcha_required；429/403 分开

**问题**：若 429 也走同一 10 分钟 cooldown，用户会被封死，体验差。

**修正**：

- **captcha_required**（302→验证码、正文验证码）：写入上述 cooldown（较长，如 10 分钟），并设 `detail_code=captcha_required`。
- **http_429**：不写入 cooldown，或使用**独立**的短 backoff（例如 30s～2min，可选实现）；UI 仍提示“稍后/代理”。
- **http_403**：不写入 captcha 的 cooldown；可单独较长 cooldown 或仅提示“换网络/代理”，不在本计划强制 10 分钟。

**明确**：`captcha_cooldown` 只由 **captcha_required** 触发；429/403 的 UI 提示不变，但不共用 10 分钟 cooldown。

**涉及文件**：同上；仅在 `detail_code="captcha_required"` 的分支里写 `_baidu_cooldown[key] = ...`。

---

### A.3 Warm-up 带 TTL，不要每次 search 都打

**问题**：每次搜索都 GET 首页会延迟翻倍、增加风控概率、成功率未必更高。

**修正**：

- **Warm-up 条件**：仅当（1）当前 session 从未 warm-up，或（2）距离上次 warm-up 已超过 **warm_up_ttl_seconds**（如 600～1800，可配置）时才执行 GET 百度首页。
- **状态**：Backend 实例持有 `_last_warm_up_time: float = 0`（或 0 表示未做过），同一 httpx.Client 复用；warm-up 成功后更新 `_last_warm_up_time = time.time()`。
- **同一 session**：warm-up 与 search 共用同一个 client（见 B.6），cookie 自然复用。

**验收**：连续 N 次搜索在 TTL 内只 warm-up 1 次；总请求数减少，验证码概率不因 warm-up 升高。

**涉及文件**：baidu_html.py — `warm_up_ttl_seconds` 参数，`_last_warm_up_time`，search() 内判断是否执行 warm-up。

---

## B. 建议增强点

### B.4 Warm-up 也用 follow_redirects=False，302→验证码要识别并触发 cooldown

**问题**：warm-up 若 `follow_redirects=True` 会吞掉 302，看不见“连首页都被拦截”。

**修正**：

- Warm-up 请求也使用 **follow_redirects=False**。
- 若 warm-up 响应为 302 且 Location/body href 命中 wappass/captcha：**直接**视为 `captcha_required`，设置 cooldown（按当前 key），并抛出 `WebBlockedError(detail_code="captcha_required")`，**不再**发 search 请求。
- 在 serp_meta 中记录：`warm_up_attempted=True`，`warm_up_result="captcha_redirect"` 或 `"ok"` 等，便于排查“连首页都进不去”。

**涉及文件**：baidu_html.py — warm-up 请求参数与 302 判定逻辑（复用现有 wappass/captcha 检测）。

---

### B.5 Cooldown 剩余时间传给 UI

**问题**：用户看到“冷却中”却不知道多久，会反复点。

**修正**：

- 抛出 `WebBlockedError(captcha_cooldown)` 时，在 **message** 或 **serp_meta** 中带上 `cooldown_seconds_remaining`（或 `cooldown_until` + 前端算剩余秒数）。
- WebBlockedError 增加可选字段：`detail_code="captcha_cooldown"` 时，`serp_meta` 含 `cooldown_until`（时间戳）、`cooldown_remaining_sec`（整数）。
- RunDetailsDrawer / TaskContext 展示：“约 N 分钟后重试”（由 `cooldown_remaining_sec` 换算）。

**涉及文件**：errors.py（WebBlockedError 可选 serp_meta）、baidu_html.py（构造 serp_meta）、task_context.py（文案）、RunDetailsDrawer.tsx（显示 N 分钟）。

---

### B.6 Session 生命周期：Backend 持有一个 Client，实例级复用

**问题**：每次 search 都 `with httpx.Client()...` 则无 session 意义，cookie 不保留。

**修正**：

- **BaiduHtmlSearchBackend** 持有私有 **httpx.Client**（延迟创建）：例如 `_client: Optional[httpx.Client] = None`，首次 search（或 warm-up）时创建并复用。
- **同一 backend 实例**内多次 search 共用该 client（warm-up TTL 内只打一次首页，同上）。
- **close**：提供 `close()` 方法（`if self._client: self._client.close(); self._client = None`）；若 catalog 或 runner 有生命周期钩子（如 `close_providers()`），在关闭 provider 时调用 backend.close()，避免泄漏。

**涉及文件**：baidu_html.py（_client 懒创建、close）；catalog.py 或 WebProvider（若需在 close_providers 时关掉 backend，需约定 Backend 协议带 close）。

---

## C. 测试与验收调整

### C.7 通过注入 client_factory / http_client 做单测，避免粗 mock get

**问题**：直接 mock `httpx.Client#get` 太粗，易与真实行为偏离，且难以断言请求顺序、follow_redirects、cooldown 下不发请求。

**修正**：

- **注入**：BaiduHtmlSearchBackend 接受可选 **client_factory**（或 **http_client** 接口）：例如 `client_factory: Callable[[], httpx.Client] = httpx.Client`，构造 client 时用 `self._client_factory()` 而非写死 `httpx.Client(...)`。单测中注入一个 **FakeClient** 或 **MockTransport**，记录每次请求的 URL、follow_redirects、顺序。
- **单测验证**：
  - 请求次数与顺序：TTL 内第一次 search → 1 次 warm-up + 1 次 search；第二次 search（TTL 内）→ 仅 1 次 search。
  - follow_redirects：warm-up 与 search 均为 False（见 B.4）。
  - cooldown 分支：触发 captcha_required 后，同一 key 再次 search 不发起任何 HTTP 请求，直接抛 captcha_cooldown。
  - key 隔离：换 proxy 或 UA 后，新 key 可立即请求。
- **不依赖真实网络**：全部通过注入的 client/transport 完成，避免 flaky。

**涉及文件**：baidu_html.py（构造函数增加 client_factory）；test_baidu_html_backend.py（注入 Mock/FakeClient，断言请求序列与 cooldown 行为）。

---

## 实现顺序建议

1. **Cooldown 按 key + 仅 captcha 触发**（A.1、A.2）— 数据结构与写入点。
2. **Session 单 Client + close**（B.6）— 为 warm-up 复用与测试打基础。
3. **Warm-up TTL + 条件执行**（A.3）— 只在该发时才发 warm-up。
4. **Warm-up 302 识别与 cooldown**（B.4）— follow_redirects=False，命中则 captcha_required + cooldown，serp_meta 记录 warm_up_*。
5. **Cooldown 剩余时间进 UI**（B.5）— serp_meta / message / RunDetailsDrawer。
6. **注入 client_factory + 单测**（C.7）— 请求顺序、cooldown 不发请求、key 隔离可量化验收。

---

## 验收清单（修订后）

- [ ] 未开代理触发 captcha → 该 key 进入 cooldown；开代理后（新 key）可立刻再试。
- [ ] 仅 captcha_required 写入长 cooldown；429/403 不写入或短 backoff，不共用 10 分钟。
- [ ] TTL 内连续 N 次 search 只 warm-up 1 次；超过 TTL 再 warm-up 1 次。
- [ ] Warm-up 若 302→验证码则直接 captcha_required + cooldown，serp_meta 含 warm_up_attempted / warm_up_result。
- [ ] UI 显示“约 N 分钟后重试”（cooldown_remaining_sec）。
- [ ] 单测通过注入 client 验证：请求顺序、cooldown 不发请求、key 隔离。
