# CI 修复说明

## 问题
CI 失败，错误：`ModuleNotFoundError: No module named 'sqlalchemy'`

## 原因
CI 配置中没有安装 `packages/memory` 包，而该包现在依赖 `sqlalchemy`。

## 解决方案

需要在 `.github/workflows/ci.yml` 文件中更新 Python 依赖安装步骤。

### 需要修改的文件
`.github/workflows/ci.yml` 第 18 行

### 当前配置：
```yaml
python -m pip install -e "apps/core-api[test]" -e "apps/agent-worker[test]" -e "packages/protocol[test]"
```

### 需要改为：
```yaml
python -m pip install -e "packages/memory" -e "packages/runtime" -e "packages/protocol[test]" -e "apps/core-api[test]" -e "apps/agent-worker[test]"
```

## 手动修复步骤（推荐）

由于 GitHub 权限限制，无法自动推送 workflow 文件更改，需要手动更新：

### 方法 1：在 GitHub Web 界面更新（最简单）

1. 打开 PR #33：https://github.com/Nana77mi/LonelyCat/pull/33
2. 点击 "Files changed" 标签
3. 找到 `.github/workflows/ci.yml` 文件
4. 点击文件右上角的 "..." 菜单，选择 "Edit file"
5. 将第 18 行更新为：
   ```yaml
   python -m pip install -e "packages/memory" -e "packages/runtime" -e "packages/protocol[test]" -e "apps/core-api[test]" -e "apps/agent-worker[test]"
   ```
6. 滚动到底部，填写 commit 信息：`fix: 在 CI 中添加 packages/memory 依赖安装`
7. 选择 "Commit directly to the feature/memory-spec-v0.1 branch"
8. 点击 "Commit changes"

### 方法 2：在本地更新并推送

如果您有 workflow 权限的 GitHub token：

```bash
# 编辑文件
# 将第 18 行更新为上面的新配置

# 提交并推送
git add .github/workflows/ci.yml
git commit -m "fix: 在 CI 中添加 packages/memory 依赖安装"
git push
```

## 已完成的修复

- ✅ 更新了 `apps/core-api/pyproject.toml`，添加了对 `lonelycat-memory` 的依赖声明
- ✅ 已准备好 CI 配置的修复代码（但由于权限限制无法自动推送）
- ✅ 创建了此说明文档

## 验证

修复后，CI 应该能够：
1. 成功安装 `packages/memory` 包（包含 sqlalchemy 依赖）
2. 成功导入 `memory` 模块
3. 运行所有测试
