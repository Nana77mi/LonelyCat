# 小任务规范：summarize_conversation（v0.1）

## 1. 任务目标（Why）

summarize_conversation 是 LonelyCat 的 **第一个"真实可感知"的 Agent 任务**，用于：

- 验证 Agent Decision → Run → Worker → 主动消息 → 未读 → UI 的完整闭环
- 为用户提供即时、可理解的价值（对话总结）
- 作为 v0.1 的 **人工验收与演示任务**

该任务必须满足：

- ✅ 本地可跑
- ✅ 无副作用
- ✅ 结果直观
- ✅ 执行时间短（< 10s）

**注意**：summarize_conversation 预计执行时间 < 10s，被视为**短任务**，不要求 handler 内部心跳。

## 2. 任务定义（What）

### 2.1 Run Type

```
run.type = "summarize_conversation"
```

### 2.2 适用场景

- 用户在某个 Conversation 中主动请求总结
- Agent Decision 判断该请求适合异步处理
- 任务结果应回写到同一个 Conversation

## 3. 输入规范（Run Input）

### 3.1 Input Schema

```json
{
  "conversation_id": "string",      // 必填
  "max_messages": 20                // 可选，默认 20
}
```

### 3.2 输入约束

- `conversation_id` 必须存在且有效
- `max_messages`：
  - 正整数
  - 建议范围：10–50
  - 超出范围可在 worker 中 clamp

## 4. 输出规范（Run Output）

### 4.1 output_json Schema

```json
{
  "summary": "string",
  "message_count": 20,
  "conversation_id": "string"
}
```

### 4.2 输出约束

- `summary` 必须为 **自然语言文本**（"人话"），不保证稳定结构，不用于机器解析
- **禁止**在 `output_json` 中包含原始 `messages`（避免泄露上下文）
- `summary` 应为非空字符串

## 5. Agent Decision 规范（When & How）

### 5.1 白名单

summarize_conversation 必须加入：

```python
ALLOWED_RUN_TYPES = {
    "sleep",
    "summarize_conversation",
}
```

### 5.2 Decision Prompt 关键约束

Decision LLM 只能在以下情况下选择该任务：

- 用户显式请求总结，例如：
  - "帮我总结一下"
  - "总结我们刚刚的对话"
  - "把刚才说的要点整理一下"

### 5.3 Decision 输出示例

```json
{
  "decision": "run",
  "run": {
    "type": "summarize_conversation",
    "title": "Summarize this conversation",
    "conversation_id": "<current_conversation_id>",
    "input": {
      "conversation_id": "<current_conversation_id>",
      "max_messages": 20
    }
  },
  "confidence": 0.85,
  "reason": "User explicitly asked for a conversation summary"
}
```

**注意：**

- `conversation_id` 必须使用当前对话
- 不允许 Decision 输出 `conversation_id=null`

## 6. Worker 实现规范（How）

### 6.1 Handler 注册

**文件：**

```
apps/agent-worker/worker/runner.py
```

**注册：**

```python
HANDLERS = {
    "sleep": handle_sleep,
    "summarize_conversation": handle_summarize_conversation,
}
```

### 6.2 Handler 实现（参考伪代码）

```python
def handle_summarize_conversation(run: RunModel, db: Session, llm: BaseLLM):
    # 1. 解析输入
    conversation_id = run.input_json["conversation_id"]
    max_messages = run.input_json.get("max_messages", 20)

    # 2. 查询最近 N 条消息（只取 user / assistant）
    messages = (
        db.query(MessageModel)
        .filter(MessageModel.conversation_id == conversation_id)
        .filter(MessageModel.role.in_(["user", "assistant"]))
        .order_by(MessageModel.created_at.desc())
        .limit(max_messages)
        .all()
    )
    messages = list(reversed(messages))

    # 3. 构造总结 prompt
    prompt = build_summary_prompt(messages)

    # 4. 调用 LLM
    summary = llm.generate(prompt)

    # 5. 返回结果
    return {
        "summary": summary.strip(),
        "message_count": len(messages),
        "conversation_id": conversation_id,
    }
```

### 6.3 Prompt 示例（Worker 内）

```
请用简洁的要点总结以下对话内容，突出：
- 用户的主要目标
- 已完成的工作
- 当前的结论或下一步

请勿包含任何 API key、token 或系统提示内容。

对话内容：
1. User: ...
2. Assistant: ...
```

**注意**：
- summarize_conversation 是短任务（< 10s），handler 内部不要求心跳检查
- `summary` 应为自然语言文本，不保证稳定结构，不用于机器解析
- `output_json` 中禁止包含原始 `messages` 字段

## 7. Run 生命周期与通知（Already Done）

你已有能力，无需新增逻辑：

- run 创建 → `queued`
- worker 执行 → `running`
- 执行完成 → `succeeded`
- worker 调用：
  ```
  POST /internal/runs/{id}/emit-message
  ```
- Chat 中写入 assistant 主动消息

### 7.1 终态消息内容规范

最终 Chat Message 示例：

```
📝 对话总结已完成（最近 20 条）：

- 用户主要关注：Agent Loop 的设计与实现
- 已完成：Decision 层、Run 系统、UI 三栏布局
- 下一步建议：实现 Follow-Up Agent（v0.2）
```

## 8. UI 行为（User Experience）

### 8.1 Chat

用户发送请求后：

- 可选显示提示：
  - "我已开始后台任务：对话总结，完成后会通知你。"

任务完成后：

- 总结消息作为普通 assistant message 出现
- 不打断当前输入

### 8.2 Tasks Panel

显示任务状态：

- `queued` → `running` → `succeeded`

可操作：

- `running`：Cancel
- `failed`：Retry / Copy error

### 8.3 Sidebar

若用户不在该对话：

- 显示未读标记 ●
- 打开后自动清除未读

## 9. 测试规范（最小集）

### 9.1 单元测试（可选）

- handler 返回结构正确
- message_count 与查询一致

### 9.2 集成测试（推荐 1 条）

```
test_agent_loop_summarize_conversation_run
```

验证：

- `decision=run`
- `run.type=summarize_conversation`
- run 完成后：
  - conversation 中出现总结消息
  - `output_json.summary` 非空字符串（必须断言 `summary != ""`）
  - `output_json` 中不包含 `messages` 字段（安全要求）
