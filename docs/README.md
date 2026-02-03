# LonelyCat 架构文档（Docs-Driven Development）

本目录是 LonelyCat 的**权威架构依据**，所有实现必须以这里的设计为准。文档面向长期维护与团队对齐，禁止以实现细节代替设计约束。

## 建议阅读顺序

1. `00_overview/architecture.md`：全局架构视图与边界
2. `00_overview/design_principles.md`：核心设计原则
3. `00_overview/glossary.md`：术语与一致性定义
4. `01_agent_loop/`：Agent Loop 的决策、执行与主动消息
5. `02_memory_and_facts/`：事实与记忆的一等公民设计
6. `03_skills/` 与 `04_mcp/`：内部工具抽象与外部提供者协议
7. `05_integrations/`：多端接入、控制台与权限模型
8. `06_governance/`：演进与版本治理

## 文档作为实现依据的规则

- 任何功能实现必须先在文档中定义设计目标与边界。
- 若实现与文档冲突，应先更新文档并完成评审，再改动实现。
- 文档中只允许出现接口示意、状态机、数据流与约束，不出现代码实现。

## 目录结构

```
docs/
├── README.md
├── 00_overview/
│   ├── architecture.md
│   ├── design_principles.md
│   └── glossary.md
├── 01_agent_loop/
│   ├── agent_loop_overview.md
│   ├── decision_and_planning.md
│   ├── execution_and_tools.md
│   └── proactive_messages.md
├── 02_memory_and_facts/
│   ├── memory_overview.md
│   ├── fact_lifecycle.md
│   ├── scope_and_injection.md
│   └── audit_and_conflict_resolution.md
├── 03_skills/
│   ├── skills_overview.md
│   ├── skill_manifest_and_schema.md
│   ├── skill_runtime_and_invoke.md
│   ├── budgeting_and_limits.md
│   └── observability_and_errors.md
├── 04_mcp/
│   ├── mcp_overview.md
│   ├── mcp_as_skill_provider.md
│   ├── mcp_adapter_design.md
│   ├── discovery_and_invocation.md
│   └── security_and_secrets.md
├── 05_integrations/
│   ├── connectors.md
│   ├── web_console.md
│   └── identity_and_permissions.md
└── 06_governance/
    ├── versioning_and_compatibility.md
    ├── documentation_workflow.md
    └── future_evolution.md
```
