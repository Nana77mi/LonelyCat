# Phase 2.1 - Runtime Integration & Reliability

**Status**: IN PROGRESS
**Started**: 2026-02-09
**Focus**: 运营与可靠性（不是新功能）

---

## 架构验收反馈总结

### 当前级别
✅ **AgentOS MVP** - 完整的"安全执行闭环"已达成

已具备：
- 结构化意图（ChangePlan）
- 结构化变更（ChangeSet + checksum）
- 判决（WriteGate）
- 原子执行（temp+rename、old_content match）
- 失败自动回滚（备份+恢复）
- 验证与健康检查（Verifier/Health Checker）
- 全链路审计（ExecutionContext）

### 识别的缺口

**缺口 A: 运行时集成边界**
- Executor 是库还是独立服务？
- 鉴权、并发、超时、幂等、重放、锁的处理

**缺口 B: 健康检查真实化**
- Health Checker 需要从占位符变为可执行、可审计、可回滚触发条件

---

## Phase 2.1 实现内容

### 1. 稳态规则文档（已完成 ✓）

#### A) agent/workflows/execute_changeset.md
**唯一允许的执行路径**

```
1. Intent Decomposition
2. Planner → ChangePlan + ChangeSet
3. WriteGate → GovernanceDecision
4. Decision Check: ALLOW or NEED_APPROVAL+approved
5. Executor → Apply (atomic + rollback-safe)
6. Verification + Health Checks
7. Audit Trail
```

**强制规则**：
- Rule 1: No Direct File Writes（必须通过 workflow）
- Rule 2: Evaluation Before Execution（必须获得 decision）
- Rule 3: Checksum Verification（必须验证完整性）
- Rule 4: Atomic Execution with Rollback（必须原子执行）
- Rule 5: Audit Trail（必须记录审计）

**禁止绕过**：
- ❌ 跳过 WriteGate
- ❌ 跳过验证
- ❌ 忽略判决
- ❌ 修改已批准的 ChangeSet
- ❌ 跳过失败回滚

#### B) agent/policies/default.yaml（已扩展 ✓）
**新增 Executor 规则**

```yaml
executor:
  # 路径约束
  allowed_paths: ["apps/**", "packages/**", "docs/**", ...]

  # 执行约束
  constraints:
    max_files_touched: 50
    max_patch_lines: 5000
    max_execution_time: 300
    max_step_time: 60

  # 风险要求
  require_health_checks_for_risk: [MEDIUM, HIGH, CRITICAL]
  require_verification_for_risk: [LOW, MEDIUM, HIGH, CRITICAL]

  # 必须人工审查
  always_review_categories:
    - "**/*schema*.py"  # 数据库模式
    - "**/security/**"  # 安全代码
    - "agent/policies/**"  # 策略文件
    - "packages/executor/**"  # Executor 自身
    - "packages/governance/**"  # 治理系统

  # 并发控制（Phase 2.1）
  concurrency:
    enabled: true
    lock_scope: "repository"
    lock_timeout: 600

  # 幂等性（Phase 2.1）
  idempotency:
    enabled: true
    key_format: "plan_id + changeset.checksum"
    cached_result_ttl: 3600
```

---

### 2. 关键安全特性（已实现 ✓）

#### A) ExecutionLock - 仓库级互斥锁
**文件**: `packages/executor/execution_lock.py` (330 lines)

**特性**：
- 跨平台文件锁（O_CREAT | O_EXCL 原子创建）
- 防止并发写入造成文件损坏
- 防止备份/回滚互相干扰
- 支持超时和stale锁清理

**使用**：
```python
lock_mgr = LockManager(workspace_root, timeout_seconds=600)

with lock_mgr.lock_execution(exec_id, plan_id):
    # 执行变更（串行化）
    executor.execute(plan, changeset, decision)
```

**锁元数据**：
```json
{
  "execution_id": "exec_xxx",
  "plan_id": "plan_xxx",
  "acquired_at": "2026-02-09T12:00:00",
  "pid": 12345,
  "hostname": "machine-name"
}
```

#### B) IdempotencyManager - 防重复执行
**文件**: `packages/executor/idempotency.py` (280 lines)

**特性**：
- 基于 `hash(plan_id + changeset.checksum)` 生成执行ID
- 缓存执行结果（1小时TTL）
- 允许重试失败的执行
- 自动清理过期记录

**使用**：
```python
idem_mgr = IdempotencyManager(workspace, ttl_seconds=3600)

with IdempotencyCheck(idem_mgr, plan_id, checksum) as check:
    if check.already_executed:
        return check.previous_record  # 返回缓存结果

    # 执行
    result = execute_changeset()
    check.record_result(result)
```

**执行记录**：
```python
@dataclass
class ExecutionRecord:
    execution_id: str
    plan_id: str
    changeset_id: str
    checksum: str
    status: str  # "completed" or "failed"
    executed_at: str
    files_changed: int
    verification_passed: bool
    message: str
    ttl_seconds: int
```

---

### 3. Executor 集成（已完成 ✓）

**修改**: `packages/executor/executor.py`

#### 新增初始化参数：
```python
def __init__(
    self,
    workspace_root: Path,
    dry_run: bool = False,
    use_locking: bool = True,  # NEW
    use_idempotency: bool = True  # NEW
):
    self.lock_manager = LockManager(workspace) if use_locking else None
    self.idempotency_manager = IdempotencyManager(workspace) if use_idempotency else None
```

#### 新执行流程：
```python
def execute(plan, changeset, decision) -> ExecutionResult:
    # 1. Idempotency check
    if use_idempotency:
        with IdempotencyCheck(mgr, plan.id, changeset.checksum) as check:
            if check.already_executed:
                return cached_result  # 返回缓存

            # 2. Acquire lock
            if use_locking:
                with lock_mgr.lock_execution(exec_id, plan.id):
                    result = _do_execute(...)  # 实际执行
            else:
                result = _do_execute(...)

            # 3. Record result
            check.record_result(...)
            return result
```

---

### 4. 验收测试（已创建 ✓）

**文件**: `packages/executor/tests/test_acceptance.py` (500+ lines)

#### 5 个强制验收用例：

**Test 1: Concurrent Writes** ⏳
- 场景：两条 changeset 同时执行
- 期望：只有一个执行，另一个被锁阻塞
- 防止：文件损坏、备份冲突、竞态条件

**Test 2: Duplicate Submission** ✅
- 场景：同一 changeset 重复提交
- 期望：第二次检测到重复，返回缓存结果
- 防止：重复修改文件、资源浪费

**Test 3: Partial Failure Rollback** ⏳
- 场景：第2步失败（验证失败）
- 期望：第1步（文件修改）必须回滚
- 防止：部分状态、drift、手工清理负担

**Test 4: Checksum Tampering** ✅
- 场景：ChangeSet 内容被篡改，checksum 不匹配
- 期望：Executor 拒绝执行（安全违规）
- 防止：执行被篡改的变更、绕过 WriteGate

**Test 5: Path Boundary Violation** ⏳
- 场景：尝试写入 forbidden path（.env）
- 期望：WriteGate DENY + Executor 也拒绝（双重防御）
- 防止：修改关键文件、泄露秘密

---

## 当前测试状态

### 已通过 ✅
1. **Checksum Tampering** - Executor 正确检测并拒绝被篡改的 ChangeSet
2. **Duplicate Submission** - Idempotency 工作正常，返回缓存结果

### 进行中 ⏳
3. **Concurrent Writes** - 锁机制已实现，测试调整中
4. **Partial Failure Rollback** - 回滚逻辑存在，测试验证中
5. **Path Boundary** - WriteGate 规则调整中

---

## 关键设计模式

### 1. Execution Lock Pattern
```python
# 使用文件锁实现 repo-level mutex
lock_file = workspace/.lonelycat/locks/execution.lock

# 原子创建（O_CREAT | O_EXCL）
fd = os.open(lock_file, os.O_CREAT | O_EXCL | O_WRONLY)
if success:
    write_metadata()
    execute_changeset()
    release_lock()
```

### 2. Idempotency Key Pattern
```python
# 确定性 ID 生成
execution_id = hash(plan_id + changeset.checksum)

# 查询缓存
if cache[execution_id] exists and not expired:
    return cached_result
else:
    result = execute()
    cache[execution_id] = result
```

### 3. Defense in Depth
```
Layer 1: Planner - 生成完整计划
Layer 2: WriteGate - 策略验证（forbidden paths, risk levels）
Layer 3: Executor - 二次验证（checksum, path boundaries, approval）
Layer 4: Rollback - 失败自动恢复
```

---

## 待完成项（Phase 2.1 后续）

### 优先级 1: 测试修复
- [ ] 调整并发测试（可能需要更短的超时）
- [ ] 验证回滚测试中的文件恢复
- [ ] 确认 WriteGate forbidden path 检查

### 优先级 2: 真实服务集成
- [ ] Health Checker 连接真实服务（core-api, agent-worker）
- [ ] 服务重启支持
- [ ] 数据库连接检查

### 优先级 3: 生产就绪
- [ ] Artifact 存储规范（备份、日志、diff 落盘）
- [ ] 执行历史持久化（SQLite）
- [ ] 监控和告警集成

---

## 文件清单

### 新增文件
```
agent/workflows/execute_changeset.md        - 强制执行路径文档 (430 lines)
packages/executor/execution_lock.py         - 仓库级锁 (330 lines)
packages/executor/idempotency.py            - 幂等性管理 (280 lines)
packages/executor/tests/test_acceptance.py  - 验收测试 (500+ lines)
```

### 修改文件
```
agent/policies/default.yaml                 - 新增 executor 规则 (+100 lines)
packages/executor/__init__.py               - 导出新组件
packages/executor/executor.py               - 集成锁和幂等 (+150 lines)
```

---

## 关键洞察

### 1. 运营 vs 功能
Phase 2.1 不是新功能，而是**让现有功能可运营**：
- 不是"能跑"，而是"可运营"
- 不是"demo"，而是"生产级"

### 2. 稳态规则的重要性
文档化的规则防止：
- 未来自己绕过治理
- 外部工具绕过安全检查
- AI 忘记约束条件

### 3. 双重防御
即使 WriteGate 被绕过（理论上不可能），Executor 仍然防御：
- Checksum 验证
- Path 边界检查
- Approval 验证

### 4. 幂等性 = 可重试
幂等性不仅防止重复，还让系统**可恢复**：
- 失败后可以安全重试
- 不用担心"已经执行了一半"
- 结果可预测

---

## 下一阶段路线图

### Phase 2.1 完成标准
- ✅ 文档完整（workflows + policies）
- ✅ 锁机制实现
- ✅ 幂等性实现
- ⏳ 5个验收测试全部通过
- ⏳ 真实服务集成

### Phase 3: Reflection Loop（后续）
- 只读汇总：过去 N 次执行的成功/失败原因
- 产出 proposals：新的 health_checks 建议、policy 调整建议
- 不自动改 policy（policy 永远需要审批）

### Phase 1.5.1: LLM 集成（最后）
- LLM 只做 reasoning：解释、生成 ChangeSet 草案
- Planner/WriteGate/Executor 全 deterministic
- 避免把不确定性引入主链路

---

## 总结

**Phase 2.1 核心价值**：
1. **并发安全** - ExecutionLock 防止文件损坏
2. **幂等性** - IdempotencyManager 防止重复执行
3. **文档化约束** - workflows + policies 防止绕过
4. **验收测试** - 生产级验证，不是单元测试

**系统现状**：
```
✓ Phase 0: Cognition Layer
✓ Phase 1: Governance Layer (WriteGate)
✓ Phase 1.5: Planner Layer
✓ Phase 2: Executor Layer
→ Phase 2.1: Runtime Integration (85% complete)
```

**离"稳态上线"还差**：
- 验收测试全通过
- 真实服务集成
- 生产监控和告警

**但已经达到**：可控、可审计、可回滚的自主执行！
