# 架构总览

## 设计目标

- 建立“本地优先、可多端接入、可扩展工具”的统一平台架构。
- 让 Agent Loop、Memory/Facts、Skills/MCP 成为稳定的长期演进基座。
- 支持多端连接与可观测运维，同时保证安全与权限可控。

## 核心概念

- **Core API**：平台的统一入口与治理层，负责路由、权限、预算、审计与状态管理。
- **Agent Worker**：执行 Agent Loop（决策 → 执行 → 主动消息）的工作单元。
- **Skills**：内部统一工具抽象，所有工具调用都通过 Skills 体系完成。
- **MCP**：外部工具接入协议，被视为“外部 Skill Provider”。
- **Facts / Memory**：一等公民的事实与记忆体系，进入系统消息用于决策。
- **Connector**：对接 QQ/WeChat/Web 等渠道的接入层。
- **Web Console**：任务、记忆、工具、预算与审计的可视化控制面板。

## 架构边界与分层

### 逻辑分层

1. **接入层（Connectors）**
   - 负责多端消息收发、用户身份映射、回调与事件桥接。
2. **平台治理层（Core API）**
   - 统一处理权限、预算、审计、事实注入、任务编排。
3. **执行层（Agent Worker）**
   - 执行 Agent Loop 并调用 Skills/MCP 提供的工具。
4. **工具层（Skills/MCP）**
   - Skills 为内部抽象，MCP 为外部提供者。
5. **记忆层（Facts/Memory）**
   - 事实与记忆的生命周期与审计能力。

### 数据流（文字描述）

- 用户消息从 Connector 进入，经过 Core API 进行身份解析、权限校验、预算核算。
- Core API 基于任务上下文加载 Facts/Memory，并注入 system message。
- Agent Worker 执行决策与计划，调用 Skills（含 MCP 提供的工具）。
- 工具调用与结果回写被统一审计，并在必要时反馈用户。

## 关键约束

- 所有工具调用必须走统一技能抽象（Skills），不允许绕过。
- Facts 注入 system message，而非 user message，确保推理一致性。
- 所有外部工具必须通过 MCP 接入并由适配器转为 Skills。

## 非目标

- 不定义具体模型供应商与模型细节。
- 不涉及具体数据库或消息队列选型。
- 不描述任何函数级实现与代码细节。

## 未来演进方向

- 将多 Agent 协作纳入统一任务编排模型。
- 引入更细粒度的预算策略与用户可配置治理策略。
- 提升 Web Console 的可视化能力以支持大规模审计与合规。
