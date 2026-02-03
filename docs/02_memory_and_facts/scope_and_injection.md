# Scope 与注入策略

## 设计目标

- 约束事实的作用范围，避免跨域污染。
- 保证 Agent 以一致方式获取上下文。

## Scope 定义

- **global**：跨项目、跨会话共享的长期事实。
- **session**：仅当前会话可见的临时事实。
- **project**：特定项目或任务域内共享的事实。

## 注入策略

- Facts 统一注入 **system message**，不注入 user message。
- 注入时按 scope 和权限过滤。
- 注入内容包含事实摘要、来源与状态。

## 事实注入示意（文本）

```
[system]
Facts:
- fact_id: F-001
  scope: project
  status: accepted
  summary: "用户偏好使用中文输出"
  source: "user_confirmation"
```

## 非目标

- 不规定事实的排序算法与检索实现。

## 未来演进方向

- 支持“事实视图”差异化（面向不同 Agent 角色）。
