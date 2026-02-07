# PR 创建标准流程

## 标准请求模板（复制使用）

当你需要创建 PR 时，使用以下模板：

```
创建 PR 到 GitHub，确保 PR 可以直接 merge：
1. 运行测试确保通过：make test-py
2. 检查 lint 错误
3. 确保所有更改已提交
4. 基于最新的 main 分支
5. PR 描述包含完整的变更说明和测试验证
6. 等待 CI 检查通过后再告诉我
```

## 详细步骤（Cursor 会自动执行）

### 1. 代码质量检查
- ✅ 运行测试：`make test-py` 或 `pytest`
- ✅ 检查 lint：使用 `read_lints` 工具
- ✅ 确保没有语法错误

### 2. Git 状态检查
- ✅ 检查未提交的更改：`git status`
- ✅ 确保基于最新 main：`git fetch origin && git rebase origin/main`
- ✅ 检查提交历史：`git log --oneline origin/main..HEAD`

### 3. 创建 PR
- ✅ 使用清晰的标题（feat/fix/docs 前缀）
- ✅ 提供完整的 PR 描述
- ✅ 等待 CI 检查完成

### 4. 验证 PR 状态
- ✅ 检查 checks：`gh pr checks <number>`
- ✅ 确认 mergeable：`gh pr view <number> --json mergeable`
- ✅ 所有检查通过

## 当前 PR 状态示例

✅ **PR #50 状态**：
- mergeable: MERGEABLE ✅
- CI checks: 全部通过 ✅
- 可以立即 merge

## 注意事项

1. **Branch Protection Rules**：如果仓库设置了必须 review，需要等待 review 或自行 approve
2. **Codex Limits**：不影响 mergeable 状态，只是自动化 review 不可用
3. **Draft PR**：如果 PR 标记为 draft，需要先转换为 ready for review

## 快速检查命令

```bash
# 检查 PR 是否可以 merge
gh pr view <number> --json mergeable,statusCheckRollup

# 查看所有 checks
gh pr checks <number>

# 如果所有检查通过且 mergeable=true，就可以直接 merge
```
