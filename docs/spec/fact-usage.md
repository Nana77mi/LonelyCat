# Fact 使用规范（LonelyCat Memory System）

本文定义 LonelyCat 中 Fact（长期记忆）的概念、使用方式、注入规范，以及验收标准。
目标是确保 Agent 在跨对话、多任务场景下具备一致、可控、可验证的长期记忆能力。

## 1. 什么是 Fact（定义）

### 1.1 基本定义

Fact 是 LonelyCat 中表示「已确认、可长期使用的用户事实信息」的最小单位。

它具有以下特征：

✅ 已被用户明确确认（Accept）

✅ 可跨对话（Conversation）使用

✅ 可被 Agent 在决策与回复中引用

❌ 不等同于聊天历史（History）

❌ 不随单个对话结束而失效

示例 Fact：

```json
{
  "key": "likes",
  "value": "cats",
  "scope": "global",
  "status": "active"
}
```

### 1.2 Fact 与其他概念的区别

| 概念 | 是否持久 | 是否跨对话 | 用途 |
|------|---------|-----------|------|
| Chat History | ❌ | ❌ | 维持当前对话连贯性 |
| Proposal | ❌ | ❌ | 候选记忆，等待确认 |
| Fact | ✅ | ✅ | 长期记忆、个性化、上下文 |
| Run Output | ✅ | ⚠️ | 任务结果，不一定是事实 |

## 2. Fact 的系统定位

### 2.1 Fact 是 Agent 的「长期记忆层」

LonelyCat 的 Agent 记忆分为三层：

```
┌───────────────────────────┐
│ Chat History (短期工作记忆) │
├───────────────────────────┤
│ Facts (长期记忆，Fact)     │ ← 本文重点
├───────────────────────────┤
│ System / Persona           │
└───────────────────────────┘
```

- **Chat History**：回答"刚刚说了什么"
- **Facts**：回答"你是谁 / 你喜欢什么 / 你之前说过什么"
- **System / Persona**：约束 Agent 行为与风格

### 2.2 Fact 的职责边界

Fact 只负责陈述已知事实，不负责：

- 推理
- 任务调度
- 临时上下文

例如：

✅ "用户喜欢猫"

❌ "用户可能会喜欢宠物用品"

❌ "用户这次想买猫粮"

## 3. Fact 的使用标准（核心）

这是本系统中最重要的一节。

### 3.1 Fact 的生命周期（简述）

```
User Message
   ↓
Proposal（候选记忆）
   ↓ Accept
Fact（active）
   ↓
被注入到 Agent 的对话 / 决策中
```

### 3.2 Fact 的注入时机（强制）

Fact 必须在以下所有场景中被注入：

- ✅ 普通聊天回复（chat_flow） - **已实现**
- ✅ Agent Decision（是否创建 Run） - **已实现**
- ❌ 长任务 Handler（如 summarize_conversation） - **未实现**

否则视为实现不完整。

### 3.3 Fact 的注入方式（强制规范）

#### ✅ 当前实现方式（与规范有差异）

**chat_flow（responder.py）**：
- 将 active_facts 格式化为文本，注入到 **user message** 中
- 格式：`已知的用户信息：\n{facts_text}\n\n用户消息：{user_message}`

**Agent Decision（agent_decision.py）**：
- 将 active_facts 以 JSON 格式注入到 **prompt** 中
- 格式：`Active facts:\n{json.dumps(active_facts)}`

#### 📋 规范推荐方式（待实现）

**推荐格式**：System Message 注入（messages 模式）

在调用 LLM 前，必须将 active facts 注入到 messages 中，作为 system role 的一部分。

推荐格式：

```
The following are known facts about the user.
You MUST use them when relevant and MUST NOT ask the user
for information already stated here.

[KNOWN FACTS]
- preference.likes_animals: cats
- profile.language: zh-CN
[/KNOWN FACTS]
```

对应 messages 示例：

```json
{
  "role": "system",
  "content": "...facts content..."
}
```

#### ❌ 不允许的方式

- ❌ 仅存入数据库但不注入 LLM
- ❌ 混入普通 user / assistant message（当前实现方式）
- ❌ 只在 history 中出现
- ❌ 仅用于 summarize，不用于 chat

### 3.4 Agent 行为约束（硬规则）

当 active facts 中存在相关信息时，Agent 必须：

✅ 优先使用 Fact 回答问题

❌ 不得反问用户已知事实

❌ 不得假装"不知道"

例如：

| 用户问题 | Fact 存在 | 合法回答 | 非法回答 |
|---------|----------|---------|---------|
| 我喜欢什么？ | likes=cats | "你喜欢猫" | "我不知道你喜欢什么" |
| 我喜欢猫吗？ | likes=cats | "是的" | "你喜欢猫吗？" |

## 4. Scope 与可见性规则

### 4.1 Scope 定义

| Scope | 含义 |
|-------|------|
| global | 跨所有对话可用 |
| project | 仅在同一 project 下可用 |
| session | 仅在当前 conversation 有效 |

### 4.2 当前实现状态

**✅ 已实现**：
- Memory Store 支持 global/project/session scope
- API 支持按 scope 查询

**❌ 未实现**：
- Agent 代码中硬编码使用 `scope="global"`
- 未支持 project 和 session scope 的自动注入
- `chat_flow` 和 `AgentDecision` 都只查询 global scope

### 4.3 推荐使用规范（v0.x）

- 用户偏好 / 身份信息 → global
- 项目相关事实 → project
- 临时上下文 → 不应使用 Fact（用 history）

## 5. 验收标准（必须满足）

### 5.1 人工验收标准（必过）

#### ✅ 用例 1：跨对话记忆（已实现）

**对话 A**：
- 用户："我喜欢猫，请记住这一点"
- 系统：创建 Proposal，用户接受，生成 Fact（scope=global）

**新建对话 B**：
- 用户："我喜欢猫吗？"
- 系统：**应回答"是的，你喜欢猫"**（使用 Fact）

**当前状态**：✅ 已实现（chat_flow 中注入 active_facts）

#### ❌ 用例 2：Agent Decision 使用 Facts（部分实现）

**场景**：
- 用户："帮我总结一下对话"
- Agent Decision 应能使用 Facts 来理解上下文

**当前状态**：✅ 已实现（Agent Decision 中注入 active_facts）

#### ❌ 用例 3：长任务 Handler 使用 Facts（未实现）

**场景**：
- `summarize_conversation` 任务应能使用 Facts 来提供更准确的总结

**当前状态**：❌ 未实现（`runner.py` 中的 `_handle_summarize_conversation` 未注入 active_facts）

### 5.2 技术验收标准

#### ✅ 已实现

1. **Fact 存储与查询**
   - ✅ Proposal → Fact 生命周期
   - ✅ 按 scope 和 status 查询
   - ✅ Fact 的创建、更新、撤销

2. **chat_flow 注入**
   - ✅ 获取 global scope 的 active facts
   - ✅ 格式化为文本注入到 user message
   - ✅ 通过 `_format_active_facts()` 函数格式化

3. **Agent Decision 注入**
   - ✅ 获取 global scope 的 active facts
   - ✅ 注入到 decision prompt 中

#### ❌ 未实现 / 不符合规范

1. **注入方式不符合规范**
   - ❌ chat_flow：应注入到 system message，实际注入到 user message
   - ❌ Agent Decision：应注入到 system message，实际注入到 prompt

2. **Scope 支持不完整**
   - ❌ 只使用 global scope，未支持 project/session scope
   - ❌ 未根据 conversation_id 或 project_id 自动选择 scope

3. **长任务 Handler 未注入**
   - ❌ `summarize_conversation` 任务未注入 active_facts
   - ❌ 其他长任务 Handler 也可能未注入

4. **Policy Prompt 可能需要改进**
   - ⚠️ 当前 prompt 可能不够明确要求使用 Facts

## 6. 实现细节（当前代码）

### 6.1 chat_flow 实现

**文件**：`apps/agent-worker/agent_worker/chat_flow.py`

```python
# 获取 active facts
active_facts = memory_client_in_use.list_facts(
    scope="global", status="active"
)

# 传递给 responder
assistant_reply, _memory_hint = responder.reply_with_messages(
    persona,
    user_message,
    history_messages,
    active_facts,  # 注入
    trace=trace,
)
```

**文件**：`apps/agent-worker/agent_worker/responder.py`

```python
# 格式化 facts
facts_text = _format_active_facts(active_facts)

# 注入到 user message（不符合规范）
current_user_content = (
    f"已知的用户信息：\n{facts_text}\n\n"
    f"用户消息：{user_message}"
)
messages.append({"role": "user", "content": current_user_content})
```

### 6.2 Agent Decision 实现

**文件**：`apps/core-api/app/services/agent_decision.py`

```python
# 获取 active facts
active_facts = agent_decision.get_active_facts()  # 只查询 global scope

# 注入到 prompt（不符合规范）
if active_facts:
    facts_json = json.dumps(active_facts, ensure_ascii=False, indent=2)
    context_parts.append(f"\nActive facts:\n{facts_json}")
```

### 6.3 summarize_conversation 实现

**文件**：`apps/agent-worker/worker/runner.py`

```python
def _handle_summarize_conversation(...):
    # ❌ 未注入 active_facts
    prompt = self._build_summary_prompt(messages)
    summary = llm.generate(prompt)
```

## 7. 待实现功能

### 7.1 高优先级

1. **修改注入方式为 System Message**
   - 修改 `responder.py`：将 facts 注入到 system message
   - 修改 `agent_decision.py`：将 facts 注入到 system message（如果使用 messages API）

2. **长任务 Handler 注入 Facts**
   - 修改 `runner.py`：在 `_handle_summarize_conversation` 中注入 active_facts
   - 其他长任务 Handler 也需要注入

3. **支持 Project/Session Scope**
   - 修改 `chat_flow`：根据 conversation_id 查询 session scope facts
   - 修改 `AgentDecision`：支持 project scope（需要 project_id）

### 7.2 中优先级

1. **改进 Policy Prompt**
   - 更明确地要求 LLM 使用 Facts
   - 明确禁止反问已知事实

2. **Fact 格式化优化**
   - 当前格式：`- likes: cats`
   - 可考虑更结构化的格式

### 7.3 低优先级

1. **Fact 使用统计**
   - 记录哪些 Facts 被使用
   - 用于优化 Fact 质量

2. **Fact 冲突检测**
   - 检测新 Proposal 与现有 Facts 的冲突
   - 自动提示用户

## 8. 相关文件

### 核心实现文件

- `apps/agent-worker/agent_worker/chat_flow.py` - chat_flow 主流程
- `apps/agent-worker/agent_worker/responder.py` - 回复生成，注入 facts
- `apps/core-api/app/services/agent_decision.py` - Agent Decision，注入 facts
- `apps/agent-worker/worker/runner.py` - 长任务 Handler（未注入 facts）
- `apps/agent-worker/agent_worker/memory_client.py` - Memory 客户端
- `packages/memory/memory/facts.py` - Fact 存储实现

### 规范文档

- `docs/spec/memory.md` - Memory 系统规范
- `docs/spec/agent-loop.md` - Agent Loop 规范

## 9. 总结

### ✅ 已完成

1. Fact 定义和存储系统
2. Proposal → Fact 生命周期
3. chat_flow 中注入 active_facts（注入到 user message）
4. Agent Decision 中注入 active_facts（注入到 prompt）
5. 基础格式化函数 `_format_active_facts()`

### ❌ 未完成 / 不符合规范

1. 注入方式不符合规范（应注入到 system message）
2. 只使用 global scope，未支持 project/session scope
3. 长任务 Handler（如 summarize_conversation）未注入 facts
4. Policy Prompt 可能需要更明确

### 📋 下一步行动

1. 修改注入方式为 System Message（高优先级）
2. 在长任务 Handler 中注入 facts（高优先级）
3. 支持 project/session scope（中优先级）
4. 改进 Policy Prompt（中优先级）
