# CI 修复说明

## 问题
CI 失败，错误：`ModuleNotFoundError: No module named 'sqlalchemy'`

## 原因
CI 配置中没有安装 `packages/memory` 包，而该包现在依赖 `sqlalchemy`。

## 解决方案

需要在 `.github/workflows/ci.yml` 文件中更新 Python 依赖安装步骤：

**当前配置（第 18 行）：**
```yaml
python -m pip install -e "apps/core-api[test]" -e "apps/agent-worker[test]" -e "packages/protocol[test]"
```

**需要改为：**
```yaml
python -m pip install -e "packages/memory" -e "packages/runtime" -e "packages/protocol[test]" -e "apps/core-api[test]" -e "apps/agent-worker[test]"
```

## 手动修复步骤

1. 在 GitHub 上打开 PR #33
2. 点击 "Files changed" 标签
3. 找到 `.github/workflows/ci.yml` 文件
4. 点击文件右侧的 "..." 菜单，选择 "Edit file"
5. 将第 18 行更新为上面的新配置
6. 提交更改（会作为新的 commit 添加到 PR）

或者，您也可以：
1. 在本地手动编辑 `.github/workflows/ci.yml`
2. 提交并推送更改（如果您的 GitHub token 有 workflow 权限）

## 已完成的修复

- ✅ 更新了 `apps/core-api/pyproject.toml`，添加了对 `lonelycat-memory` 的依赖声明
- ✅ 已准备好 CI 配置的修复（但由于权限限制无法自动推送）
