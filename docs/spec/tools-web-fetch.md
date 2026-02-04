# web.fetch 工具合同

## 输入

- **url**：string，必填，minLength=1；仅允许 `http://` 或 `https://` 开头。
- **timeout_ms**：integer，可选；未传时由 provider 默认（如 15000）。

## 输出（canonical）

**唯一支持的返回形状**：`{ "url", "status_code", "content_type", "text", "truncated" }`

- **url**：string，请求的 URL。
- **status_code**：integer，HTTP 状态码。
- **content_type**：string，响应 Content-Type（可为空串）。
- **text**：string，正文（HTML 经提取可见文本，或 plain text 原样）；非文本响应时为空串。
- **truncated**：boolean，是否因最大长度截断。

## 错误码

- **InvalidInput**：url 空、非 http(s)、格式非法。
- **Timeout**：请求超时。
- **NetworkError**：DNS/连接失败。
- **WebBlocked**：403/429 或 body 含 captcha/unusual traffic/blocked。
- **WebParseError**：解析异常（v0 较少使用）。

## 限制

- 仅允许 **http://** 与 **https://**；禁止 file://、ftp://、内网段等（v0 仅做 scheme 白名单，内网/本地可后续加）。
- 最大文本长度由 env **WEB_FETCH_TEXT_MAX** 可配（建议 50k～150k 字符）；超出截断并设 `truncated: true`。

## Backend

- **stub**（默认）：不打网，返回固定 canonical；用于 CI/离线。
- **httpx**：真实 httpx GET；设置 `WEB_FETCH_BACKEND=httpx` 启用。
- 未知值：记录 warning 并回退 stub。

详见 [tools-web-search.md](tools-web-search.md) 中 research_report 与 web 工具关系。
