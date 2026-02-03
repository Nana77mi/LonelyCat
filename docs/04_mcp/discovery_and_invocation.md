# 发现与调用

## 设计目标

- 定义 MCP 工具发现与调用的治理路径。
- 确保外部工具调用可控与可审计。

## 发现流程（文字描述）

1. MCP Server 提供工具清单与版本信息。
2. MCP Adapter 拉取清单并生成 Skill Manifest。
3. Skill Registry 注册外部 Skill 并标注来源。

## 调用流程（文字描述）

- Executor 发起 Skill 调用请求。
- Runtime 根据 Manifest 路由至 MCP Adapter。
- Adapter 调用 MCP Server 并返回统一结果。

## 设计约束

- 发现与调用必须记录审计与变更日志。
- 版本变更需触发兼容性检查。

## 非目标

- 不定义具体发现协议细节与缓存策略。

## 未来演进方向

- 支持订阅式发现与动态变更通知。
