# 决策与规划

## 设计目标

- 明确决策阶段的输入、输出与约束。
- 让计划成为可审计、可执行的结构。

## 核心概念

- **决策输入**：用户意图、Facts/Memory、任务状态、预算与权限。
- **计划结构**：由步骤、工具需求、预期输出构成的可序列化计划。
- **不可执行计划处理**：在预算或权限不足时显式反馈。

## 计划示意（JSON）

```json
{
  "goal": "完成用户请求",
  "steps": [
    {
      "id": "step-1",
      "action": "invoke_skill",
      "skill": "search.docs",
      "inputs": {
        "query": "..."
      },
      "requires": {
        "budget": "medium",
        "permissions": ["docs:read"]
      }
    }
  ],
  "fallbacks": [
    {
      "condition": "budget_exceeded",
      "strategy": "summarize_without_tool"
    }
  ]
}
```

## 设计约束

- 计划必须显式声明预算与权限要求。
- 计划中的工具调用只能引用 Skills 抽象。
- 决策结果必须可回放与审计。

## 非目标

- 不定义模型如何生成计划。
- 不规定计划的最小或最大步数。

## 未来演进方向

- 支持多计划分支与并行执行的规划结构。
- 支持基于历史审计数据的计划优化。
