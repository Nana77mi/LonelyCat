# 主动消息路由决策表

> 本文档定义了 LonelyCat 系统中主动消息的路由规则、策略和生命周期。
> 详细说明了不同消息来源、会话（Conversation）和通道（Channel）之间的交互逻辑，以及消息在不同状态下的流转。

---

## 术语 (Terminology)

- **Channel**: 消息下发的通道，例如 IM、SMS、Email 等。渠道 ID（如 wechat, qq, slack ...）
- **Conversation**: 一个对话链路，基于 Channel 和 ID 识别。一个由特定渠道（from channel）上由特定用户发起/持续的会话。
- **Message**: 消息内容。会话中的一条消息。
- **Origin**: 消息发起方，例如 Scheduler、Connector、System、Email 等。消息来源（如 scheduler, connector, system, email）。
- **Anchor**: 锚定到一个对话，由 Conversation ID 和 Channel Thread ID 决定。消息上一个会话关联（如 conversation_id, channel_thread_id）。

---

## 1. 消息匹配规则表 (Message Matching Rule Table)

### 1.1 规则总览

| 消息来源 | conversation_id | channel_thread_id | Is New Conversation | Existing Conversation | 备注 |
|---------|----------------|-------------------|-------------------|---------------------|------|
| MCP HTTP API | ✓ | ✓ | ✓ | ✓ | 可指定 conversation_id 或 channel_thread_id，但不能同时指定 |
| MCP Scheduler | ✗ | ✗ | ✓ | ✗ | 必须创建新会话 |
| MCP Connector | ✗ | ✗ | ✓ | ✗ | 必须创建新会话 |
| MCP System Agent | ✗ | ✗ | ✓ | ✗ | 自动生成 conversation_id |
| MCP System | ✗ | ✗ | ✓ | ✗ | 自动生成 conversation_id |

**说明：**
- `Conversation ID` 是唯一对话 ID
- `channel_thread_id` 是唯一通道对话 ID
- ✓ 表示必须指定该字段
- ✗ 表示不能指定该字段
- ✔ 表示可以指定该字段

### 1.2 规则匹配注意事项

**优先级规则：**
1. `conversation_id` 匹配 → `channel_thread_id` 失效
2. `isNewConversation` 匹配 → `channel_thread_id` 和 `conversation_id` 失效
3. `API` 只能触发一种情况（`isNewConversation` 或 `attachedToConversation`）

**互斥规则：**
- `conversation_id` 与 `channel_thread_id` 互斥，不能同时指定
- `conversation_id` 为全局唯一 ID
- `channel_thread_id` 为通道级别唯一 ID

---

## 2. 消息处理策略 (Conversation ID)

### 2.1 策略总览

| 策略 | 优先级 | 备注 |
|-----|--------|------|
| 有 Conversation ID | 1 | 优先使用指定对话 ID |
| 优先使用指定对话 ID | ✓ | 查找 Conversation ID 对应的对话 |
| 创建/查找对话 | ✓ | 如果不存在则创建新对话 |

### 2.2 策略说明

**策略：优先使用指定对话 ID > 创建/查找对话**

| 消息来源 | Conversation ID 匹配 | 说明 |
|---------|---------------------|------|
| 新建会话 (New conversation) | ✗ | 不支持，需要 conversation_id |
| 现有会话 (Existing conversation) (API触发) | ✓ | 使用传入的 conversation_id |
| 自动生成 (Auto-generated) (system/program) | ✓ | 自动生成 conversation_id |

**注意事项：**
- 所有 proactive message 必须锚定到一个 conversation id（通过 API 传入或系统生成）
- 如果 conversation id 不存在，系统会自动创建 conversation id

---

## 3. 消息处理策略 (Channel)

### 3.1 策略总览

**策略：优先使用指定通道 ID > 创建/查找通道**

| Origin | Conversation ID 匹配 | Channel 匹配 | 备注 |
|--------|---------------------|--------------|------|
| MCP HTTP API | ✗ | ✓ | 只能指定 `channel_thread_id`、`channel_id`、`channel_type` |
| MCP Scheduler | ✓ | ✓ | 匹配 conversation_id 和 channel |
| MCP Connector | ✓ | ✓ | 匹配 conversation_id 和 channel |
| MCP System | ✓ | ✓ | 匹配 conversation_id 和 channel |

**注意事项：**
- `channel_thread_id` 与 `conversation_id` 互斥，当两者同时提供时以 `conversation_id` 为准
- `Origin` 决定了消息路由的起点和策略

---

## 4. 消息的生命周期 (创建, 路由, 暂停)

### 4.1 消息状态

| 状态 | 描述 | 备注 |
|------|------|------|
| `pending` | 等待发送 | 默认状态 |
| `sending` | 正在发送 | 系统自动转换 |
| `sent` | 已发送 | 成功发送后的状态 |

### 4.2 消息类型

| 类型 | 描述 | 备注 |
|------|------|------|
| `text` | 普通文本消息 | 支持纯文本和 markdown 格式 |
| `rich_text` | 富文本消息 | 支持格式化内容 |
| `image` | 图片消息 | 支持图片附件 |

---

## 5. 消息内容与缓存决策

### 5.1 消息内容 (纯文本)

**消息来源：**
- API 调用
- Scheduler（计划任务）
- Connector（连接器）

**内容限制：**
- 最长 1024 字符

**存储规则：**
- 存储在 `db.Message.content` 字段

### 5.2 消息类型处理

| 消息类型 | 状态 | 存储位置 |
|---------|------|---------|
| 普通消息 (Normal Message) | ✓ 成功 | `message.data.payload.text` |
| 失败 (Failed) | ✗ 失败 | `message.data.payload.error.reason` |
| 取消 (Canceled) | ⭐ 取消 | `message.data.payload.cancel.reason` |

**备注：**
- 文本消息支持纯文本和 markdown 格式

---

## 6. 外部接口输入的最小必要字段

### 6.1 必填字段

| 字段 | 类型 | 说明 | 必填 |
|------|------|------|------|
| `channel_type` | string | 渠道类型 | ✓ |
| `channel_thread_id` | string | 渠道线程 ID | ✓ |
| `channel_user_id` | string | 渠道用户 ID | ✓ |

**备注：**
- 必须传入 `conversation_id` & `channel_thread_id` & `channel_user_id` 之一，否则会抛出异常
- 如果无法从这些字段之一自动获取会话，则不能发送消息

---

## 7. 最小实现清单 (MVP)

### 7.1 核心功能

- [x] `conversation_fact_graph_id` - 会话事实图谱 ID
- [x] 消息的路由规则 - 实现消息匹配和路由逻辑
- [x] 消息的创建发送和状态更新 - 实现消息生命周期管理
- [x] Skill 调度 - 支持技能调度功能
- [x] 消息的生命周期 - 实现消息状态流转
- [x] Scheduler 消息发送 - 支持计划任务消息发送

### 7.2 实现细节

**会话管理：**
- `conversation.start_group()` - 启动会话组

**消息锚点处理：**
- 根据不同来源的消息锚点处理
- `proactiveMessage`: 机器人主动发起的消息（单聊）
- `systemMessage`: `system.conversation.create`

**历史消息：**
- `chatPage` 历史消息支持

---

## 8. 总结

### 8.1 核心原则

1. **唯一性**: `conversation_id` 为全局唯一，`channel_thread_id` 为通道级别唯一
2. **互斥性**: `conversation_id` 与 `channel_thread_id` 不能同时指定
3. **优先级**: 指定 `conversation_id` > 创建/查找对话
4. **锚定性**: 所有 proactive message 必须锚定到一个 conversation id

### 8.2 实现要求

- 所有消息必须能够正确路由到目标会话
- 支持多种消息来源的统一处理
- 实现完整的消息生命周期管理
- 提供清晰的状态转换机制

---

## 附录

### A. 相关文档

- [Memory Spec](./memory.md) - 内存规范文档
- [Web Console UI Behavior](./web-console-ui-behavior.md) - Web Console UI 行为规范

### B. 更新历史

- v0.1 - 初始版本，定义主动消息路由决策表
