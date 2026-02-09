# Phase 1.5 - Planner Layer 实现总结

## 完成时间
2026-02-09

## 核心洞察

**用户架构判断**（正确）：
> "真正缺的不是 Executor，而是 Planner Layer"

### 为什么这是关键一步？

**问题诊断**：
- Planning unstable（规划不稳定）
- Risk reasoning unpredictable（风险推理不可预测）
- Workflow generation inconsistent（工作流生成不一致）

**根本原因**：
```
LLM = planner + reasoning + tool selection + risk thinking (太杂糅)
```

**正确架构**：
```
Planner Layer (deterministic) → 决策编排
    ↓
LLM (reasoning engine) → 推理执行
    ↓
ChangePlan → 结构化意图
    ↓
WriteGate → 治理验证
```

## 实现组件

### 1. State Machine (`packages/planner/state_machine.py`)
**状态定义**：
- INTENT → ANALYSIS → PLAN_GENERATION → GOVERNANCE_CHECK → EXECUTION_READY

**关键特性**：
- 确定性转换（deterministic transitions）
- 每个状态的工具限制（tool restrictions）
- 转换历史追踪（transition history）

**工具限制示例**：
```python
ANALYSIS: {
    "read_file", "grep", "glob"  # 只读工具
}

PLAN_GENERATION: {
    "read_file", "generate_diff"
}

GOVERNANCE_CHECK: {
    "governance.evaluate"  # 只能调用治理API
}
```

### 2. Risk Shaper (`packages/planner/risk_shaper.py`)
**职责**：自动生成安全字段（不依赖LLM记忆）

**自动生成**：
- `rollback_plan`: "git revert <commit> && restart services"
- `verification_plan`: "Run tests, check health endpoints"
- `health_checks`: ["GET /health returns 200", ...]

**为什么重要**？
```
Before: LLM 忘记 rollback → WriteGate NEED_APPROVAL → 重试
After: Planner 自动添加 rollback → WriteGate ALLOW (首次通过率高)
```

### 3. Intent Decomposer (`packages/planner/decomposer.py`)
**职责**：将用户意图分解为阶段

**分类**：
- FIX_BUG → 需要分析 + 回归测试
- ADD_FEATURE → 需要分析 + API设计
- UPDATE_DOCS → 跳过分析 + 低风险
- INVESTIGATE → 只读分析

**输出**：
```python
DecomposedIntent(
    intent_type=IntentType.FIX_BUG,
    needs_analysis=True,
    analysis_requirements=[READ_CODE, TRACE_FLOW],
    suggested_approach="Identify root cause → Design fix → Test",
    estimated_risk="medium"
)
```

### 4. Planner Orchestrator (`packages/planner/orchestrator.py`)
**总协调器**：整合所有组件

**工作流**：
1. 接收 user intent
2. Decompose intent（确定性分解）
3. State machine transitions（按规则转换）
4. Risk shaping（自动补全安全字段）
5. 输出 ChangePlan + ChangeSet

**输出**：
```python
{
    "context": StateContext,
    "decomposed": DecomposedIntent,
    "plan": ChangePlan,     # 包含自动生成的 rollback/verification
    "changeset": ChangeSet
}
```

## 测试结果

```
===== test session starts =====
collected 16 items

test_planner.py ................  [100%]

16 passed, 46 warnings in 0.09s
```

**测试覆盖**：
- State machine transitions ✓
- Intent decomposition ✓
- Risk shaping ✓
- Orchestrator workflow ✓
- Tool validation ✓
- Full integration flow ✓

## Demo演示结果

```
Test 1: Fix memory conflict resolution bug
  Type: fix_bug
  Needs Analysis: True
  State: intent → analysis → plan_generation → governance_check

Test 2: Add new web search provider
  Type: add_feature
  Needs Analysis: False
  State: intent → plan_generation → governance_check

Test 3: Update WriteGate documentation
  Type: update_docs
  Needs Analysis: False
  Risk: high (governance component)

Test 4: Optimize database query performance
  Type: optimize
  Needs Analysis: True
  Risk: high (database component)
```

## 架构对比

### Before Planner (不稳定)
```
User: "Fix bug"
  ↓
LLM: 随机思考 → 可能想到rollback, 可能忘记
  ↓
WriteGate: 事后拦截 "缺少rollback_plan" → NEED_APPROVAL
  ↓
重试...（低效）
```

### After Planner (稳定)
```
User: "Fix bug"
  ↓
Planner: 分解为 ANALYSIS → PLAN_GENERATION
Planner: 强制使用只读工具（安全）
Planner: 自动添加 rollback/verification（完整）
  ↓
WriteGate: 验证 → ALLOW（首次通过率高）
  ↓
EXECUTION_READY
```

## 关键设计模式

### 1. Deterministic Decomposition
规则驱动（不是LLM突发奇想）：
```python
if "fix" in intent:
    intent_type = FIX_BUG
    needs_analysis = True
    tools = ["read_file", "grep", "trace_flow"]
```

### 2. Risk Shaping Injection
自动补全（不是LLM记忆）：
```python
plan.rollback_plan = auto_generate_rollback(affected_paths)
plan.verification_plan = auto_generate_verification(operation_type)
```

### 3. State-Based Tool Routing
状态决定工具（不是LLM选择）：
```python
if state == ANALYSIS:
    allowed_tools = ["read_file", "grep"]  # 只读
elif state == PLAN_GENERATION:
    allowed_tools = ["generate_diff"]
```

## 为什么系统"活起来"？

### 以前（事后筛选）
```
AI thinking randomly → Governance filtering (事后拦截)
```
- LLM 自由发挥 → 不一致
- WriteGate 事后拦截 → 重试成本高
- 低 ALLOW 率 → 用户体验差

### 现在（事前塑造）
```
Planner shaping thinking → Governance validating (事前塑造)
```
- Planner 塑造思维 → 一致性
- WriteGate 验证完整性 → 首次通过率高
- 高 ALLOW 率 → 流畅体验

## Phase 1.5 边界

### 已实现（MVP）
- ✅ State Machine（确定性状态转换）
- ✅ Intent Decomposition（规则驱动分解）
- ✅ Risk Shaping（自动生成安全字段）
- ✅ Planner Orchestrator（总协调）
- ✅ ChangePlan生成（带自动补全）

### 未实现（Phase 1.5.1）
- ❌ 实际LLM调用（reasoning engine）
- ❌ 真实代码分析（ANALYSIS阶段）
- ❌ 真实diff生成（ChangeSet内容）

**Phase 1.5 MVP**：
- 证明架构正确性
- Planner生成完整ChangePlan
- Ready for WriteGate integration

## 与 WriteGate 集成

```python
# Phase 1.5 output
planner_result = orchestrator.create_plan_from_intent("Fix bug")
plan = planner_result["plan"]
changeset = planner_result["changeset"]

# Phase 1 WriteGate evaluation
decision = writegate.evaluate(plan, changeset)

# Phase 2 Executor (future)
if decision.is_approved():
    executor.apply(changeset)
```

## 文件清单

```
packages/planner/
  __init__.py               - 包导出
  state_machine.py          - 状态机定义（270 lines）
  risk_shaper.py            - 风险塑造（310 lines）
  decomposer.py             - 意图分解（330 lines）
  orchestrator.py           - 总协调器（270 lines）
  tests/
    test_planner.py         - 测试套件（290 lines, 16/16 passed）

demo_planner.py             - 演示脚本（95 lines）
```

## 下一步

### Phase 1.5.1 - LLM Integration
将 Planner 与真实 LLM 集成：
- ANALYSIS 阶段：LLM 读取代码并理解
- PLAN_GENERATION 阶段：LLM 生成真实 diff
- Planner 提供约束，LLM 提供推理

### Phase 2 - Host Executor
- 安全应用 ChangeSet
- 验证计划自动运行
- 失败自动回滚

## 结论

**Phase 1.5 - Planner Layer 实现完成** ✓

**核心价值**：
- 确定性编排（不是随机行为）
- 自动安全补全（不依赖LLM记忆）
- 状态驱动工具路由（不是LLM决策）

**系统现状**：
```
Cognition Layer (agent/) ✓
Governance Engine (WriteGate) ✓
Planner Layer (Orchestrator) ✓ ← NEW!
```

**为什么现在可以考虑 Phase 2 Executor**：
- Planner 确保 ChangePlan 完整（有 rollback/verification）
- WriteGate 确保 ChangePlan 安全（通过治理检查）
- Executor 现在是"安全的 raw power"（被 Planner 和 WriteGate 约束）

**下一阶段 ready for Phase 2** 🚀
