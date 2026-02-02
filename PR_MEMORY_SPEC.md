# 实现 Memory Spec v0.1 - 重构 memory 系统

## 📋 概述

本次 PR 根据 Memory Spec v0.1 完整重构了 LonelyCat 的 memory 系统，从 `subject/predicate/object` 三元组模型迁移到 `key/value` 模型，并实现了完整的生命周期管理、scope 支持、冲突解决和审计日志功能。

## ✨ 主要变更

### 🔄 数据模型重构
- **从三元组到键值对**：`subject/predicate/object` → `key/value`
- **新增 Scope 支持**：`global` / `project` / `session`
- **版本管理**：Fact 支持版本号，用于追踪更新历史
- **Source Reference**：每个 Proposal 和 Fact 都包含来源引用（kind, ref_id, excerpt）

### 📊 存储层升级
- **SQLite 持久化**：从内存字典迁移到 SQLite 数据库
- **SQLAlchemy ORM**：使用 ORM 进行数据库操作
- **自动表创建**：首次运行时自动创建数据库表结构

### 🔄 生命周期管理

#### Proposal 生命周期
- `pending` → `accepted` / `rejected` / `expired`
- 支持 TTL（Time To Live）自动过期
- 支持手动过期操作

#### Fact 生命周期
- `active` → `revoked` / `archived`
- `revoked` / `archived` → `active` (reactivate)
- 支持版本追踪（version 字段）

### ⚖️ 冲突解决机制
- **overwrite_latest**：更新现有 fact，版本号递增
- **keep_both**：创建新的 fact，保留所有历史记录
- **智能策略选择**：根据 key 的特征自动选择策略（可配置）

### 📝 审计系统
- **完整审计日志**：所有状态变更都记录审计事件
- **变更追踪**：update 操作记录 before/after diff
- **查询支持**：支持按 target_type、target_id、event_type 过滤

### 🌐 API 更新
- 更新所有 REST API 端点以适配新模型
- 新增端点：`/proposals/{id}/expire`、`/facts/{id}/archive`、`/facts/{id}/reactivate`、`/audit`
- 更新请求/响应格式

### 🎨 前端更新
- 更新 TypeScript 类型定义
- 重构 MemoryPage 组件以支持新功能
- 更新 FactDetailsDrawer 组件
- 添加 scope 选择器

### 🤖 Agent Worker 更新
- 更新 MemoryClient 以适配新 API
- 更新所有调用方（run.py, chat_flow.py, update_cli.py, retract_cli.py）
- 保持向后兼容的接口（内部转换）

## 📁 文件变更

### 新增文件
- `packages/memory/memory/db.py` - SQLAlchemy 数据库模型和配置
- `packages/memory/memory/audit.py` - 审计日志系统
- `docs/spec/memory.md` - Memory Spec v0.1 规范文档

### 重构文件
- `packages/memory/memory/schemas.py` - 新的数据模型定义
- `packages/memory/memory/facts.py` - MemoryStore 实现（完全重写）
- `apps/core-api/app/api/memory.py` - API 端点更新
- `apps/web-console/src/api/memory.ts` - TypeScript API 客户端更新
- `apps/web-console/src/pages/MemoryPage.tsx` - UI 组件更新
- `apps/agent-worker/agent_worker/memory_client.py` - 客户端更新

### 测试文件
- `packages/memory/tests/test_facts_store.py` - 完全重写
- `apps/core-api/tests/test_memory.py` - 更新以适配新 API
- `apps/agent-worker/tests/test_memory_client_*.py` - 更新测试

## 🎯 核心功能

### 1. Proposal 管理
- ✅ 创建 Proposal（支持 payload、source_ref、confidence、scope_hint）
- ✅ 接受 Proposal（支持冲突解决策略）
- ✅ 拒绝 Proposal
- ✅ 过期 Proposal（手动或 TTL 自动）

### 2. Fact 管理
- ✅ 创建 Fact（通过接受 Proposal）
- ✅ 更新 Fact（通过 overwrite_latest 策略）
- ✅ 撤销 Fact（revoke）
- ✅ 归档 Fact（archive）
- ✅ 重新激活 Fact（reactivate）
- ✅ 按 key 查询 Fact
- ✅ 按 scope 过滤 Fact

### 3. Scope 隔离
- ✅ Global scope：全局可用
- ✅ Project scope：项目级别隔离（需要 project_id）
- ✅ Session scope：会话级别隔离（需要 session_id）

### 4. 冲突解决
- ✅ 自动检测 key 冲突
- ✅ 支持 overwrite_latest 策略
- ✅ 支持 keep_both 策略
- ✅ Key policy 配置（数据库表或硬编码默认值）

### 5. 审计日志
- ✅ 记录所有状态变更
- ✅ 记录变更差异（before/after）
- ✅ 支持查询和过滤

## 🔧 技术细节

### 数据库配置
- **默认数据库**：`sqlite:///./lonelycat_memory.db`
- **环境变量**：`LONELYCAT_MEMORY_DB_URL`（可配置）
- **查询日志**：`LONELYCAT_MEMORY_DB_ECHO=true`（开发调试）

### 依赖更新
- 新增：`sqlalchemy>=2.0`

### 数据库表结构
- `proposals` - 存储 Proposal
- `facts` - 存储 Fact
- `audit_events` - 存储审计事件
- `key_policies` - 存储 key 的冲突解决策略（可选）

## ⚠️ 破坏性变更

**这是破坏性变更**，旧的数据模型和 API 不再支持：

1. **数据模型变更**：`subject/predicate/object` → `key/value`
2. **状态值变更**：`ACTIVE` → `active`（小写）
3. **API 端点变更**：请求/响应格式完全改变
4. **存储后端变更**：从内存迁移到数据库

**数据迁移**：现有内存中的数据无法自动迁移，需要重新创建。

## ✅ 测试覆盖

- ✅ Proposal 生命周期测试
- ✅ Fact 生命周期测试
- ✅ 冲突解决策略测试
- ✅ Scope 隔离测试
- ✅ 审计日志测试
- ✅ API 端点测试
- ✅ 数据库事务测试

## 📚 文档

- `docs/spec/memory.md` - Memory Spec v0.1 完整规范
- `packages/memory/README.md` - Memory Package 使用文档

## 🧪 测试建议

1. **功能测试**
   - [ ] 创建和接受 Proposal
   - [ ] 测试冲突解决策略
   - [ ] 测试 scope 隔离
   - [ ] 测试 Fact 状态转换（revoke/archive/reactivate）
   - [ ] 测试审计日志查询

2. **数据库测试**
   - [ ] 验证数据库表创建
   - [ ] 验证数据持久化
   - [ ] 验证事务处理

3. **API 测试**
   - [ ] 测试所有 API 端点
   - [ ] 测试错误处理
   - [ ] 测试参数验证

4. **前端测试**
   - [ ] 测试 UI 组件渲染
   - [ ] 测试用户交互
   - [ ] 测试数据展示

## 📝 注意事项

1. **数据库初始化**：首次运行时会自动创建数据库表
2. **环境变量**：可通过 `LONELYCAT_MEMORY_DB_URL` 配置数据库路径
3. **向后兼容**：Agent Worker 的接口保持兼容（内部转换）
4. **测试数据库**：测试使用临时数据库，确保测试隔离

## 🔗 相关文档

- [Memory Spec v0.1](./docs/spec/memory.md)
- [Memory Package README](./packages/memory/README.md)

---

**注意**：本次 PR 包含大量重构代码，建议在合并前进行充分测试，特别是数据库迁移和 API 兼容性。
