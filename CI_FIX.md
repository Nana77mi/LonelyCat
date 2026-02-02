# CI 修复说明

## 问题 1：缺少 sqlalchemy 依赖
CI 失败，错误：`ModuleNotFoundError: No module named 'sqlalchemy'`

### 原因
CI 配置中没有安装 `packages/memory` 包，而该包现在依赖 `sqlalchemy`。

---

## 问题 2：packages/runtime 安装失败
CI 失败，错误：`ERROR: file:///.../packages/runtime does not appear to be a Python project: neither 'setup.py' nor 'pyproject.toml' found.`

### 原因
`packages/runtime` 目录没有 `pyproject.toml` 或 `setup.py` 文件，不是一个可安装的 Python 包。它通过 `conftest.py` 添加到 `sys.path`，不需要作为包安装。

## 解决方案

需要在 `.github/workflows/ci.yml` 文件中更新 Python 依赖安装步骤。

### 需要修改的文件
`.github/workflows/ci.yml` 第 18 行

### 当前配置（main 分支）：
```yaml
python -m pip install -e "apps/core-api[test]" -e "apps/agent-worker[test]" -e "packages/protocol[test]"
```

### 需要改为（问题 1 修复）：
```yaml
python -m pip install -e "packages/memory" -e "packages/runtime" -e "packages/protocol[test]" -e "apps/core-api[test]" -e "apps/agent-worker[test]"
```

### 最终版本（问题 2 修复后）：
```yaml
python -m pip install -e "packages/memory" -e "packages/protocol[test]" -e "apps/core-api[test]" -e "apps/agent-worker[test]"
```
注意：移除了 `packages/runtime`，因为它没有 `pyproject.toml`，不需要作为包安装。

## ✅ 问题已解决

CI 文件已成功推送到远程分支。通过配置 GitHub CLI 并添加 `workflow` scope，现在可以正常推送 workflow 文件了。

### 配置 GitHub Token 的步骤（已完成）

1. 使用 GitHub CLI 刷新认证并添加 `workflow` scope：
   ```bash
   gh auth refresh --hostname github.com -s workflow
   ```
2. 验证 token 包含所需 scope：
   ```bash
   gh auth status
   ```
   应该看到：`Token scopes: 'gist', 'read:org', 'repo', 'workflow'`
3. 推送更改：
   ```bash
   git push
   ```

---

## 手动修复步骤（已不需要，保留作为参考）

~~由于 GitHub 权限限制，无法自动推送 workflow 文件更改，**必须在 GitHub Web 界面手动添加**：~~

### 步骤：

1. **打开 PR #33**：https://github.com/Nana77mi/LonelyCat/pull/33

2. **点击 "Files changed" 标签**

3. **如果看不到 `.github/workflows/ci.yml` 文件**（因为权限问题无法推送），需要手动添加：
   - 点击 PR 页面右上角的 "Add file" → "Create new file"
   - 或者直接访问：https://github.com/Nana77mi/LonelyCat/new/feature/memory-spec-v0.1?filename=.github/workflows/ci.yml

4. **创建/编辑文件**，完整内容如下：

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install Python deps
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e "packages/memory" -e "packages/runtime" -e "packages/protocol[test]" -e "apps/core-api[test]" -e "apps/agent-worker[test]"
      - uses: pnpm/action-setup@v3
        with:
          version: 9
      - name: Install Node deps
        run: pnpm install
      - name: Run tests
        run: |
          python -m pytest
          pnpm -r test
```

5. **提交更改**：
   - Commit message: `fix: 在 CI 中添加 packages/memory 依赖安装`
   - 选择 "Commit directly to the feature/memory-spec-v0.1 branch"
   - 点击 "Commit changes"

## 已完成的修复

### 问题 1 修复：
- ✅ 更新了 `apps/core-api/pyproject.toml`，添加了对 `lonelycat-memory` 的依赖声明
- ✅ 本地已准备好 CI 配置的修复代码（第 18 行已更新）
- ✅ 已提交修复（commit 1a878c9）
- ✅ **已成功推送 CI 文件到远程**（commit 5ff6ac8）
- ✅ **已配置 GitHub token 并添加 `workflow` scope**，现在可以推送 workflow 文件了

### 问题 2 修复：
- ✅ **移除了 `packages/runtime` 从 CI 安装命令**（commit 0a3fb58）
- ✅ `packages/runtime` 通过 `conftest.py` 添加到 `sys.path`，pytest 会自动加载，不需要作为包安装

## 验证

修复后，CI 应该能够：
1. 成功安装 `packages/memory` 包（包含 sqlalchemy 依赖）
2. 成功导入 `memory` 模块
3. 运行所有测试

## 快速链接

- PR #33: https://github.com/Nana77mi/LonelyCat/pull/33
- 直接创建文件: https://github.com/Nana77mi/LonelyCat/new/feature/memory-spec-v0.1?filename=.github/workflows/ci.yml
