# Agent Loop Spec (v0.1)

## 1. 背景与目标

LonelyCat 目前已具备：

- 多轮对话（Conversation/Message 持久化）
- 任务执行系统（Run：抢占/续租/恢复/取消/重试）
- 主动消息通知（Run 终态 → 写入 Message，支持未读）
- 记忆系统（Proposal → Fact，审计）

Agent Loop 的目标是让 Bot 从"被动聊天"升级为"能自主挂任务并推进工作"的本地 AI 助手：

- 用户一句话既可得到即时回复，也可触发后台任务（Run）。
- 后台任务完成后，Agent 能基于结果继续下一步（多步链路）。
- 支持"自动任务"（无 conversation 上下文）以新对话未读方式送达。
- 不强依赖任何特定 agent 框架（LangGraph 等可后续接入），保持轻量、可调试、可审计。

## 2. 核心概念

### 2.1 Turn

一次用户输入及其后续系统行为的集合（可能包含：即时回复、创建任务、等待任务完成、后续回复）。

### 2.2 Plan / Decision

Agent 在每个 Turn 中先做一个决策：

- 只回复（reply-only）
- 回复 + 创建任务（reply + run）
- 仅创建任务（run-only）
- 创建多个任务并编排（multi-run）—— v0.1 可先不实现并行，仅支持串行或单个任务

### 2.3 Run

后台执行单元，具有生命周期（queued/running/succeeded/failed/canceled），可取消/重试。Run 可关联 conversation，也可无关联。

### 2.4 Loop Step

Agent Loop 的每一步是"读状态 → 决策 → 执行动作 → 写回状态"。

### 2.5 Trace / Audit

Agent Loop 的关键动作必须可追踪（至少日志；后续可落库为 AuditEvent）。

## 3. 非目标（v0.1 不做）

- 复杂工具编排框架（DAG、并行、依赖图）
- SSE/WebSocket 实时推送（先用轮询）
- 多用户协作 / 权限系统
- 复杂的"自我反思/长思考"策略（先保持可控）

## 4. 总体架构

### 4.1 组件

- **core-api**：Conversation/Message/Run API；内部通知（emit-message）；mark-read
- **agent-worker**：Run 执行；取消检查；状态更新；调用 internal API 写入主动消息
- **agent-loop**（新增逻辑层，位置可在 core-api 或 worker 内，但建议在 core-api）：
  - 在用户发消息时进行"Decision"
  - 需要时创建 Run
  - 可选：在 Run 终态后触发 follow-up（v0.2）

### 4.2 数据流（v0.1）

```
User message
  → core-api: POST /conversations/{id}/messages (chat mode)
      → AgentDecision(decide)
          → if reply: 直接生成 assistant message
          → if run: 创建 Run（conversation_id 可选）
                    + 可选先发一条 "已开始任务" 的 assistant message
      → 返回消息
Run executes in worker
  → worker complete_* → POST /internal/runs/{id}/emit-message
      → core-api 写入终态消息（assistant）
      → 更新 conversation.updated_at / last_read_at 机制决定未读
```

## 5. 行为规范（必须遵守）

### 5.1 路由规则

- 若 `run.conversation_id != null`：终态消息写回该 Conversation
- 若 `run.conversation_id == null`：创建新 Conversation（title: Task completed: ...），置未读

### 5.2 未读规则

`has_unread` 由服务端动态计算：
```
has_unread = (last_read_at is null) OR (updated_at > last_read_at)
```

用户打开对话后调用 mark-read 更新 `last_read_at`

### 5.3 幂等规则

终态消息写入必须幂等：若已存在 `source_ref.kind="run"` 且 `source_ref.ref_id=run.id` 的消息，则跳过

## 6. Agent Decision（决策层）规范

### 6.1 输入

- 当前用户消息（string）
- 近期上下文消息（message list，已由历史注入实现）
- 可选：active facts（memory）
- 可选：当前对话的最近 runs（仅用于避免重复创建任务）

### 6.2 输出：Decision JSON（v0.1）

Decision 必须严格满足 schema：

```json
{
  "decision": "reply" | "run" | "reply_and_run",
  "reply": {
    "content": "string"
  },
  "run": {
    "type": "string",
    "title": "string?",
    "conversation_id": "string|null",
    "input": { "any": "json" }
  },
  "confidence": 0.0,
  "reason": "string"
}
```

**规则：**

- `decision="reply"` → 必须提供 `reply.content`，不得提供 `run`
- `decision="run"` → 必须提供 `run`，不得提供 `reply`（或 `reply` 可为空但不展示）
- `decision="reply_and_run"` → 必须同时提供 `reply` 与 `run`
- `conversation_id`：
  - 若用户在对话里发起：必须填当前 `conversation_id`
  - 若识别为系统/自动任务：置 `null`

### 6.3 任务类型白名单

v0.1 引入白名单机制，避免"LLM 幻觉任务类型"：

- `sleep`
- `summarize_conversation`
- `index_repo`（可选）
- `fetch_web`（可选，若未来允许联网/连接器）

Decision 输出的 `run.type` 必须属于白名单，否则 fallback 为 reply-only 并附带解释。

## 7. Agent Loop（v0.1）状态机

### 7.1 在用户发消息时（同步路径）

1. 读取 conversation 上下文（历史消息、active facts）
2. 调用 Decision LLM（JSON-only wrapper）
3. 执行分支：
   - `reply`：写入 assistant message
   - `run`：创建 run；可选写入 "任务已开始" 消息
   - `reply_and_run`：两者都做
4. 返回给前端（sendMessage response）

### 7.2 在 run 完成时（异步路径）

由 worker 触发 emit-message，写入终态消息。

v0.1 不要求 run 完成后自动触发第二轮"计划/跟进"，只要能把结果送达即可。
v0.2 再加入 "follow-up decision"。

## 8. 错误处理与降级策略

### 8.1 Decision 失败

若 Decision LLM 调用失败或返回 JSON 不合法：

- fallback：reply-only（简单道歉 + 继续对话）
- 不创建 run
- 记录日志（包含 request_id / conversation_id）

### 8.2 创建 Run 失败

若 run 创建失败：

- 仍可发送 reply（若有）
- 写入一条 assistant 消息说明任务创建失败（可选）
- 记录 error

### 8.3 emit-message 失败

- emit-message 失败不能影响 run 状态（已实现）
- core-api 记录错误日志
- v0.2 可加入补发扫描任务（outbox pattern）

## 9. 幂等与并发考虑

- Decision 结果创建 run 时，建议生成 `client_request_id`（可选字段）避免用户双击导致重复任务（v0.2）
- 对 run 终态消息已通过 `source_ref` 判重实现幂等
- multi-worker 场景下，重复终态回调必须安全（幂等）

## 10. UI 行为（与 Agent Loop 的契约）

当 Decision 创建 run 时：

- Chat 中可显示一条轻量提示（可选）：
  "我已开始后台任务：{title}，完成后会通知你。"
- Tasks Panel 会显示该 run 的状态
- run 终态消息将作为普通 assistant message 出现在聊天中
- 对于 `conversation_id=null` 的 run：会出现新的未读 Conversation

## 11. 配置项（建议）

- `AGENT_LOOP_ENABLED`（默认 true）
- `AGENT_DECISION_MODEL`（默认同聊天模型或更小的模型）
- `AGENT_ALLOWED_RUN_TYPES`（白名单）
- `AGENT_DECISION_TIMEOUT_SECONDS`
- `AGENT_DECISION_FALLBACK_MODE`（reply-only）

## 12. 测试验收（v0.1）

### 必测场景

- `decision=reply`：仅回复，不创建 run
- `decision=run`：创建 run，聊天中可选提示；run 完成后写入终态消息
- `decision=reply_and_run`：同步回复 + 创建 run；终态消息可追溯
- 无 `conversation_id` 的 run：新建未读对话并写入消息
- 幂等：同一 run emit-message 两次只写一次
- cancel/failed：终态消息模板正确
- decision 输出 `run.type` 不在白名单：fallback 为 reply-only

## 13. 未来扩展（v0.2+）

### 13.1 Follow-up Loop（run 完成后继续计划）

run 完成 → 触发 `followup_decision(conversation_id, run_result)`

可产生新 run 或最终总结写回

### 13.2 Scheduler/Connector

- scheduler 触发 run（`conversation_id=null`）→ 新对话未读
- connector 同理，可按 connector 聚合固定对话

### 13.3 多渠道接入

- Conversation 绑定 `channel_type` + `channel_thread_id`
- 外部消息进入 → 映射 conversation → 走同一 Agent Loop

## 附录 A：Decision JSON Schema（建议落到代码常量）

（略，可在实现时提供严格校验）
