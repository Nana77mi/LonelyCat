# CI 修复说明

## 问题
CI 失败，错误：`ModuleNotFoundError: No module named 'sqlalchemy'`

## 原因
CI 配置中没有安装 `packages/memory` 包，而该包现在依赖 `sqlalchemy`。

## 解决方案

需要在 `.github/workflows/ci.yml` 文件中更新 Python 依赖安装步骤。

### 需要修改的文件
`.github/workflows/ci.yml` 第 18 行

### 当前配置（main 分支）：
```yaml
python -m pip install -e "apps/core-api[test]" -e "apps/agent-worker[test]" -e "packages/protocol[test]"
```

### 需要改为：
```yaml
python -m pip install -e "packages/memory" -e "packages/runtime" -e "packages/protocol[test]" -e "apps/core-api[test]" -e "apps/agent-worker[test]"
```

## 手动修复步骤（必须在 GitHub Web 界面操作）

由于 GitHub 权限限制，无法自动推送 workflow 文件更改，**必须在 GitHub Web 界面手动添加**：

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

- ✅ 更新了 `apps/core-api/pyproject.toml`，添加了对 `lonelycat-memory` 的依赖声明
- ✅ 本地已准备好 CI 配置的修复代码（第 18 行已更新）
- ✅ 已提交修复（commit 1a878c9），但由于权限限制无法推送到远程

## 验证

修复后，CI 应该能够：
1. 成功安装 `packages/memory` 包（包含 sqlalchemy 依赖）
2. 成功导入 `memory` 模块
3. 运行所有测试

## 快速链接

- PR #33: https://github.com/Nana77mi/LonelyCat/pull/33
- 直接创建文件: https://github.com/Nana77mi/LonelyCat/new/feature/memory-spec-v0.1?filename=.github/workflows/ci.yml
