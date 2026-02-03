# Skills 概览

## 设计目标

- 统一平台内所有工具抽象，屏蔽来源差异。
- 支持内部工具与外部 MCP 工具的同构调用。

## 核心概念

- **Skill**：可声明输入、输出与权限的工具单元。
- **Skill Registry**：可发现、可治理的工具目录。
- **Skill Provider**：提供 Skill 的来源，包含内置与 MCP。

## 设计共识

- Skills 是 LonelyCat 内部统一工具抽象。
- MCP 是外部 Skill Provider。
- Agent/Planner/Executor 对工具来源无感。
- 所有工具调用必须经过预算控制、权限校验、观测与审计、错误模型。

## 非目标

- 不定义具体实现语言或运行时机制。

## 未来演进方向

- 支持分级技能市场与动态加载。
