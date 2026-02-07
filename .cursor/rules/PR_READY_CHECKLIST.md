# PR 可直接合并检查清单

当你要求 Cursor 创建 PR 时，请使用以下模板，确保 PR 可以直接在 GitHub 上点击 merge：

## 标准请求模板

```
创建 PR 到 GitHub，确保：
1. ✅ 所有测试通过
2. ✅ 代码符合 lint 规范
3. ✅ PR 描述完整（包含变更说明、测试验证、影响范围）
4. ✅ 提交信息清晰（feat/fix/docs 等前缀）
5. ✅ 没有未提交的更改
6. ✅ 基于最新的 main 分支
```

## 详细检查项

### 代码质量
- [ ] 运行 `make test-py` 确保所有测试通过
- [ ] 检查 lint 错误：`read_lints` 工具
- [ ] 代码格式化一致
- [ ] 没有 console.log 或调试代码

### Git 状态
- [ ] 所有相关文件已添加到暂存区
- [ ] 提交信息清晰（使用约定式提交格式）
- [ ] 基于最新的 main 分支（`git rebase main` 或 `git merge main`）
- [ ] 没有未跟踪的文件（除非是文档）

### PR 描述
- [ ] 标题清晰（feat/fix/docs 前缀）
- [ ] 描述包含：
  - 变更概述
  - 主要文件变更
  - 测试验证
  - 影响范围
- [ ] 如果有破坏性变更，明确标注

### CI/CD
- [ ] 等待 CI 检查完成
- [ ] 所有检查通过（test、lint 等）

## 快速命令

在创建 PR 前运行：

```bash
# 1. 确保测试通过
make test-py

# 2. 检查 lint
# (在 Cursor 中使用 read_lints 工具)

# 3. 确保基于最新 main
git fetch origin
git rebase origin/main  # 或 git merge origin/main

# 4. 检查状态
git status
git log --oneline origin/main..HEAD

# 5. 创建 PR
gh pr create --title "..." --body "..." --base main
```

## 注意事项

- 如果仓库有 branch protection rules（需要 review），PR 创建后需要等待 review 或自行 approve
- Codex usage limits 不影响 PR 的 mergeable 状态，只是自动化 review 不可用
- PR 状态显示 "MERGEABLE" 且所有 checks 通过时，就可以直接 merge
