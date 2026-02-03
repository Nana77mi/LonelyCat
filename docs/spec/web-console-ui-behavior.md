# LonelyCat Web Console UI 行为规范（v0.1）

> 本文档定义了 LonelyCat Web Console 的界面布局、交互行为和用户体验规范。
> 详细说明了主动消息在 UI 层面的展示规则，以及各组件之间的交互逻辑。

---

## 0. 总体布局原则（强约束）

界面采用三栏布局：左侧固定 Sidebar，中间为聊天主区域，右侧固定 Tasks 面板。
中间聊天区域自适应伸缩，整体界面随屏幕尺寸自动缩放。

**布局结构（逻辑）：**
```
┌───────────┬───────────────────────────┬──────────────┐
│ Sidebar   │ Chat Area                  │ Tasks Panel  │
│ (Fixed)   │ (Flexible / Main Content)  │ (Fixed)      │
└───────────┴───────────────────────────┴──────────────┘
```

---

## 1. Sidebar（左侧固定）：Conversation 列表

### 1.1 基本行为

- Sidebar 始终固定在左侧
- 宽度固定（建议：240–280px）
- 不随聊天内容滚动
- 不随 Tasks 面板展开/收起而变化

### 1.2 Conversation 列表显示规则

每一条 Conversation 显示：
- 标题（title）
- 最近活动时间（updated_at → 相对时间）
- 未读标记（● 或 badge）

**未读标记规则：**
- `has_unread === true` → 显示未读标记
- 当前正在打开的 conversation 永不显示未读
- 用户点击 conversation：
  - 进入 Chat Area
  - 自动触发 `mark-read`
  - 未读标记消失

### 1.3 系统/自动任务对话

`meta_json.kind === "system_run"` 的 conversation：
- 可显示不同 icon（⚙️ / 🕒）
- 行为与普通 conversation 一致
- 系统对话不会打断当前对话，只在 Sidebar 中显示为未读

---

## 2. Chat Area（中间主区域）：聊天主体验

### 2.1 基本行为

- Chat Area 是唯一可伸缩的主区域
- 占据 Sidebar 与 Tasks Panel 之间的所有剩余空间
- 随屏幕宽度变化自动拉伸/压缩
- 内部可垂直滚动（消息历史）

### 2.2 消息显示规则

- 消息按时间顺序显示
- 主动消息（run 完成）与普通 assistant 消息无结构区别
- 可通过样式/图标区分（例如 "任务完成"标签）
- 不弹 toast、不浮窗打断聊天

### 2.3 主动消息的 UX 原则

- 如果消息写入的是当前打开的 conversation：
  - 直接出现在消息列表中
  - 不触发未读、不打断输入
- 如果消息属于其他 conversation：
  - 只在 Sidebar 中显示未读标记
  - 不自动切换 Chat Area

---

## 3. Tasks Panel（右侧固定）：任务状态与控制

### 3.1 基本行为

- Tasks Panel 固定在右侧
- 宽度固定（建议：280–320px）
- 默认始终可见（桌面端）
- 不覆盖 Chat Area，不悬浮

### 3.2 Tasks 内容规则

显示当前 conversation 相关的 runs：
- 优先显示 `conversation_id === 当前对话` 的任务
- 可选：提供 "All tasks" 切换（后续）

每个 Task 显示：
- 状态 badge（`queued` / `running` / `succeeded` / `failed` / `canceled`）
- title（或 type）
- progress（如有）

操作按钮：
- `running` / `queued` → Cancel
- `failed` → Retry / Copy error
- `succeeded` → View output（可选）

### 3.3 Tasks 与 Chat 的关系

- Tasks 是 Chat 的补充视图，不是聊天的一部分
- Tasks 的状态变化不会直接生成 UI 弹窗
- 任务终态 → 主动消息仍然写入 Chat（通过 Conversation）

---

## 4. 自动创建 Conversation 的 UI 行为

### 4.1 自动任务（无 conversation_id）

当自动/系统任务完成时：
- 新建一个 Conversation
- 显示在 Sidebar 顶部
- 标记为未读
- Chat Area 不自动切换

### 4.2 用户主动查看

用户点击该 Conversation：
- Chat Area 显示任务完成消息
- 未读清除
- Tasks Panel 显示该任务详情（如果有绑定）

---

## 5. 自动缩放与响应式规则（桌面优先）

### 5.1 桌面端（≥1200px）

- Sidebar 固定显示
- Tasks Panel 固定显示
- Chat Area 自动填充中间空间

### 5.2 中等屏幕（900–1200px）

- Sidebar 固定
- Tasks Panel 可折叠为 icon（可选，v0 可不实现）
- Chat Area 优先保证可读宽度

### 5.3 小屏 / 移动端（<900px，未来）

v0 不强制实现，但需遵守以下原则：
- 不同时显示 Sidebar + Tasks
- Conversation 列表与 Tasks 使用抽屉（Drawer）
- Chat Area 始终为主视图

---

## 6. 布局约束声明（写给未来开发者）

- Sidebar 永远固定在左侧，Tasks 永远固定在右侧
- Chat Area 是唯一的弹性区域，用于承载对话主体验
- 任何新功能（通知、搜索、设置）不得破坏该三栏结构

---

## 附录

### A. 相关文档

- [Proactive Message Routing](./proactive-message-routing.md) - 主动消息路由决策表
- [Memory Spec](./memory.md) - 内存规范文档

### B. 更新历史

- v0.1 - 初始版本，定义 Web Console UI 行为规范
