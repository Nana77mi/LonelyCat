# Skill Manifest 与 Schema

## 设计目标

- 定义 Skill 的描述与约束方式。
- 支持运行时的发现与治理。

## 核心概念

- **Manifest**：描述技能的元数据。
- **Schema**：输入、输出与错误的结构约束。
- **Capabilities**：权限、预算与作用域声明。

## Manifest 示例（JSON）

```json
{
  "name": "memory.search",
  "version": "1.0.0",
  "description": "搜索已确认的事实",
  "inputs": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "scope": {"type": "string", "enum": ["global", "session", "project"]}
    },
    "required": ["query"]
  },
  "outputs": {
    "type": "array",
    "items": {"type": "object"}
  },
  "permissions": ["facts:read"],
  "budget": "low"
}
```

## 设计约束

- Manifest 必须声明权限与预算级别。
- Schema 需能表达错误模型与可恢复信息。

## 非目标

- 不定义具体的 Schema 解析库或实现细节。

## 未来演进方向

- 支持按组织策略扩展 Manifest 字段。
