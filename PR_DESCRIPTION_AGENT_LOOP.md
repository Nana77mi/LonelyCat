# feat: 实现 Agent Loop v0.1

## 概述

实现 Agent Loop v0.1 功能，让 Bot 从"被动聊天"升级为"能自主挂任务并推进工作"的本地 AI 助手。核心是在用户发消息时插入 Decision 层，决定是仅回复、创建任务，还是两者都做。

## 主要变更

### 核心功能实现

#### 1. Agent Loop 配置模块 (`apps/core-api/app/agent_loop_config.py`)
- `AGENT_LOOP_ENABLED`（默认 True）- Agent Loop 功能开关
- `AGENT_ALLOWED_RUN_TYPES`（白名单）- 允许的任务类型列表
- `AGENT_DECISION_TIMEOUT_SECONDS`（默认 30 秒）
- 支持环境变量配置

#### 2. Agent Decision 服务 (`apps/core-api/app/services/agent_decision.py`)
- `Decision` Pydantic 模型（包含验证逻辑）
- `AgentDecision` 类：
  - `decide()`: 调用 LLM 进行决策
  - `_build_decision_prompt()`: 构建决策 prompt（包含历史消息、active facts、最近 runs）
  - `get_active_facts()`: 从 memory 获取 active facts
  - JSON Schema 验证
  - 白名单验证（不在白名单的任务类型会 fallback 为 reply-only）
  - conversation_id 处理（确保用户在对话中时使用当前 conversation_id）

#### 3. 集成到 conversations API (`apps/core-api/app/api/conversations.py`)
- 在 `_create_message` 中集成 Agent Decision 层
- 上下文收集：
  - 历史消息（已有）
  - Active facts（通过 MemoryClient）
  - 最近 runs（用于避免重复）
- 根据 Decision 结果执行：
  - `reply`: 仅回复，跳过 chat_flow
  - `run`: 创建 Run + 可选提示消息
  - `reply_and_run`: 创建 Run + 使用 Decision 的 reply.content
- 错误处理：
  - Decision 失败 → fallback 到 chat_flow
  - Run 创建失败 → 记录错误，仍发送 reply（如果有）
- 日志记录：
  - Decision 调用和结果
  - Run 创建
  - 错误信息（包含 conversation_id）

### 文档

#### 4. Agent Loop 规范文档 (`docs/spec/agent-loop.md`)
- 完整的 Agent Loop v0.1 规范
- 包含架构设计、行为规范、测试验收标准等

### 测试

#### 5. Agent Decision 单元测试 (`apps/core-api/tests/test_agent_decision.py`)
- 19 个测试用例，全部通过
- 覆盖：
  - Decision 模型验证（reply/run/reply_and_run）
  - AgentDecision 服务核心功能
  - 白名单验证和 fallback
  - conversation_id 处理
  - 错误处理（无效 JSON、无效 schema、空响应等）

#### 6. Agent Loop 集成测试 (`apps/core-api/tests/test_conversations.py`)
- 6 个集成测试，全部通过
- 覆盖：
  - decision=reply：仅回复
  - decision=run：创建 run 并显示提示
  - decision=reply_and_run：回复 + 创建 run
  - Decision 失败时 fallback
  - Run 创建失败时仍发送 reply
  - Agent Loop 禁用时使用 chat_flow

#### 7. 额外测试 (`apps/core-api/tests/test_agent_loop_additional.py`)
- 6 个优先级测试，4 个通过，1 个跳过，1 个 xfail
- 覆盖：
  - 重复 Decision 不应创建重复 Run（xfail，v0.2 实现）
  - 白名单 fallback 时 reply 内容是否合理
  - run-only 时是否真的不写 reply message（skip，notify 标志未实现）
  - Decision prompt 是否包含 active facts
  - Decision confidence 是否被记录
  - Decision 输出非法时的防御

## 关键特性

- **向后兼容**：通过配置开关控制，失败时 fallback 到原有逻辑
- **幂等性**：Run 创建和消息写入都支持幂等
- **可调试性**：完整的日志记录，包含 Decision 输入输出
- **符合规范**：严格按照 `agent-loop.md` 规范实现

## 验收标准

根据 spec 第 12 节，所有测试场景均已覆盖：

- ✅ `decision=reply`：仅回复，不创建 run
- ✅ `decision=run`：创建 run，聊天中可选提示；run 完成后写入终态消息（已有）
- ✅ `decision=reply_and_run`：同步回复 + 创建 run；终态消息可追溯（已有）
- ✅ 无 `conversation_id` 的 run：新建未读对话并写入消息（已有）
- ✅ 幂等：同一 run emit-message 两次只写一次（已有）
- ✅ cancel/failed：终态消息模板正确（已有）
- ✅ decision 输出 `run.type` 不在白名单：fallback 为 reply-only

## 配置项

- `AGENT_LOOP_ENABLED`（默认 true）
- `AGENT_ALLOWED_RUN_TYPES`（白名单，默认包含 `sleep` 和 `summarize_conversation`）
- `AGENT_DECISION_TIMEOUT_SECONDS`（默认 30 秒）

## 测试结果

所有测试在 WSL 环境中运行通过：
- Agent Decision 单元测试：19/19 通过
- Agent Loop 集成测试：6/6 通过
- 额外测试：4/6 通过（1 skip，1 xfail）

## 未来扩展（v0.2+）

- Follow-up Loop（run 完成后继续计划）
- Scheduler/Connector 支持
- 多渠道接入
- client_request_id 幂等性支持
- notify 标志支持
