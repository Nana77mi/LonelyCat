# Phase 2.4 执行谱系与反思

本文描述与 **Browser/Web 真实化** 并列的另一条线：**执行谱系、事件流、反思与基于案例的修复**。实现位于分支 `feat/phase-2.4-d-similarity-engine`，合并后与 main 的 executor、executions API 一起交付。

## 目标概览

| 块 | 目标 | 验收要点 |
|----|------|----------|
| **2.4-A** | Execution Graph（谱系） | GET /executions/{id}/lineage、GET /executions?correlation_id=、GET /executions/{id} 含 correlation_id/parent_execution_id/trigger_kind/run_id；UI Lineage 面板 |
| **2.4-D** | Similarity Engine API + UI | GET /executions/{id}/similar 返回 why_similar；详情页「Similar Executions」面板 |
| **2.4-B** | Machine-readable Event Stream | 每次执行写入 events.jsonl（step_start/step_end）；GET /executions/{id}/events?tail= |
| **2.4-C** | Reflection → Feedback Injection | reflection_hints.json 规范与生成脚本；WriteGate 仅将 hints 注入 reasons，不改变 verdict；审计字段 reflection_hints_used、hints_digest |
| **2.4-E** | Case-based Repair MVP | 失败执行可生成 repair.json（引用 evidence exec ids）；POST /executions/{id}/repair/suggest 或 scripts/suggest_repair.py |
| **2.4-F** | Engineering Closure | 本文档；prod_validation 扩展：lineage、events、similar、repair suggest 轻量检查 |

## 2.4-A Execution Graph

- **Schema**：executions 表含 correlation_id、parent_execution_id、trigger_kind、run_id（migrations 已加）。
- **API**：
  - `GET /executions/{id}/lineage?depth=` → `{ execution, ancestors, descendants, siblings }`
  - `GET /executions?correlation_id=` → 同链路执行列表
  - `GET /executions/{id}` 响应含上述 graph 字段。
- **UI**：执行详情页「Lineage」区域；列表页支持按 correlation_id 筛选。

## 2.4-D Similarity Engine

- **API**：`GET /executions/{id}/similar?limit=` → `{ similar: [{ execution, why_similar, score }] }`。
- **UI**：详情页「Similar Executions」面板，展示 why_similar 与跳转链接。

## 2.4-B Event Stream

- **约定**：`.lonelycat/executions/{exec_id}/events.jsonl`，每行 JSON：`step_start` / `step_end`，含 step_name、status、duration_seconds、error_code/error_message（若失败）。
- **写入**：Executor 每步开始/结束 append 一行。
- **API**：`GET /executions/{id}/events?tail=`，路径白名单校验。

## 2.4-C Reflection Hints

- **Schema**：ReflectionHints（hot_error_steps、false_allow_patterns、slow_steps、suggested_policy等），落盘 `.lonelycat/reflection/hints_7d.json`。
- **生成**：`scripts/generate_reflection_hints.py` 扫描 executions + steps，输出 hints。
- **WriteGate**：evaluate(..., reflection_hints_path=...) 仅将 hints 转为 reasons 附加说明，**不参与 verdict 计算**。
- **审计**：GovernanceDecision 含 reflection_hints_used、hints_digest；decision.json 落盘时包含。

## 2.4-E Case-based Repair

- **流程**：失败时调 similar，筛「同类失败后成功」的执行，提取成功案例的 plan/changeset 引用，生成 RepairProposal，写 repair.json。
- **产物**：artifacts 下 `repair.json`；可选 executions 表 is_repair、repair_for_execution_id。
- **API/脚本**：`POST /executions/{id}/repair/suggest`、`scripts/suggest_repair.py`（只生成 JSON 不执行）。

## 2.4-F Prod Validation

- lineage：存在 correlation_id 时 lineage endpoint 返回 200 且结构含 execution/ancestors/descendants/siblings。
- events：至少一次执行后 events.jsonl 存在且含 step_start/step_end。
- similar：GET /executions/{id}/similar 返回 200（空列表亦可）。
- repair suggest：可选 dry-run（只生成不执行）返回 200 或 400（非失败执行）。

每完成 A/B/C/D/E 之一，即在 prod_validation 或 pytest 中加对应轻量检查，避免回归。

---

## Phase 2.5-D：Repair 进入图谱（写入规则）

当**执行 repair**（非 suggest repair）时，在 `record_execution_start` 中必须传入：

- `parent_execution_id` = \<failed_execution_id\>
- `trigger_kind` = `"repair"`
- `is_repair` = `True`（存为 1）
- `repair_for_execution_id` = \<failed_execution_id\>
- `correlation_id` = 与失败 exec 一致（保持同链）

这样 repair 执行会出现在 lineage 的 descendants 中，并可被 lineage/similar/analytics 覆盖，系统自洽。
