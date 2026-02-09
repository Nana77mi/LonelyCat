# Windows 环境使用指南

本指南专门针对 Windows 用户，说明如何在新的 Windows 电脑上设置和运行 LonelyCat。

## 前置要求

1. **Python 3.11+**
   - 下载：https://www.python.org/downloads/
   - 安装时勾选 "Add Python to PATH"

2. **Node.js 18+**
   - 下载：https://nodejs.org/
   - 推荐安装 LTS 版本

3. **Git**
   - 下载：https://git-scm.com/download/win

## 为什么不能用 `make` 命令？

Windows 系统默认不包含 `make` 工具。Makefile 是为 Linux/WSL/macOS 设计的。

项目提供了等效的 PowerShell 脚本：
- `.\scripts\setup.ps1` → 替代 `make setup`
- `.\scripts\test-py.ps1` → 替代 `make test-py`
- `.\scripts\up.ps1` → 替代 `make up`
- `.\scripts\down.ps1` → 替代 `make down`

## 初次设置

### 1. 克隆项目

```powershell
git clone <your-repo-url>
cd LonelyCat
```

### 2. 设置执行策略（如果脚本无法运行）

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### 3. 运行安装脚本

```powershell
.\scripts\setup.ps1
```

此脚本会：
- 创建 Python 虚拟环境 (`.venv`)
- 安装所有 Python 依赖
- 安装 Node.js 依赖（使用 pnpm）

## 运行测试

```powershell
.\scripts\test-py.ps1
```

## 启动服务

```powershell
.\scripts\up.ps1
```

启动后：
- **用户界面**：http://localhost:8000
- **API 文档**：http://localhost:5173/docs

## 停止服务

```powershell
.\scripts\down.ps1
```

注意：Web 控制台在前台运行，需要在运行它的终端按 `Ctrl+C` 停止。

## 常见问题

### 问题1：虚拟环境冲突

如果你之前在 WSL/Git Bash 中创建过虚拟环境，可能会看到路径错误。

**解决方案**：删除旧的虚拟环境，重新运行 setup.ps1
```powershell
Remove-Item -Recurse -Force .venv
.\scripts\setup.ps1
```

### 问题2：node_modules 无法删除

如果看到 "Could not remove node_modules" 警告：
- 关闭 IDE 和所有终端
- 以管理员身份运行 PowerShell
- 或手动删除 `node_modules` 文件夹后重新运行

### 问题3：pnpm 未找到

启用 corepack：
```powershell
corepack enable
corepack prepare pnpm@latest --activate
```

### 问题4：端口被占用

如果端口 5173 或 8000 被占用，可以修改端口：
- 编辑 `Makefile` 或 `scripts\up.ps1` 中的端口配置
- 或在运行前设置环境变量

## 开发环境隔离

- Windows PowerShell 使用 `.venv` 虚拟环境
- WSL/Git Bash 使用 `.venv-dev` 虚拟环境
- 两者分离，避免冲突

## 与 Linux/Mac 的对应关系

| Linux/Mac | Windows PowerShell |
|-----------|-------------------|
| `make setup` | `.\scripts\setup.ps1` |
| `make test-py` | `.\scripts\test-py.ps1` |
| `make up` | `.\scripts\up.ps1` |
| `make down` | `.\scripts\down.ps1` |
| `PYTHONPATH=packages` | `$env:PYTHONPATH="packages"` |

## 技术说明

### SQLite 文件锁定问题（已修复）

在 Windows 上，SQLite 数据库文件可能在使用后保持锁定。我们已经修复了 `cache.py`，使用显式的 `try-finally` 块来确保连接被正确关闭。

**修复前的问题**：
```python
with sqlite3.connect(db_path) as conn:  # Windows 上可能不会立即释放锁
    conn.execute(...)
```

**修复后**：
```python
conn = sqlite3.connect(db_path)
try:
    conn.execute(...)
    conn.commit()
finally:
    conn.close()  # 显式关闭，确保释放锁
```

## 下一步

- 阅读主 [README.md](../README.md) 了解项目架构
- 查看 [API 文档](http://localhost:5173/docs)（需先启动服务）
- 探索 `apps/` 目录了解各个组件
