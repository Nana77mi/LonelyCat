# MCP 作为 Skill Provider

## 设计目标

- 明确 MCP 与 Skills 的关系与边界。
- 保证对上层执行者透明。

## 设计共识

- Skills 是平台内部统一工具抽象。
- MCP 是外部 Skill Provider，提供工具清单与调用接口。
- Agent/Planner/Executor 对工具来源无感。
- 所有工具调用必须经过统一的预算控制、权限校验、观测与审计、错误模型。

## 交互示意（文字描述）

1. MCP Server 暴露工具列表与 Schema。
2. MCP Adapter 将工具映射为内部 Skill Manifest。
3. Skill Runtime 以统一接口调用 MCP 工具。

## 非目标

- 不定义 MCP Server 的部署方式。

## 未来演进方向

- 允许 MCP 工具作为可动态启停的 Provider。
