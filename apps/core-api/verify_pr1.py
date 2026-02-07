"""PR-1 简单验证脚本：检查新增的 endpoints 是否正确实现"""
import re

# 读取 sandbox.py 文件
with open(r"d:\Project\lonelycat\LonelyCat\apps\core-api\app\api\sandbox.py", "r", encoding="utf-8") as f:
    content = f.read()

# 检查是否有新的 endpoints
endpoints_to_check = [
    "get_sandbox_exec_stdout",
    "get_sandbox_exec_stderr",
    "get_sandbox_exec_observation",
    "_read_output_file"
]

print("检查 PR-1 实现情况：\n")

for endpoint in endpoints_to_check:
    pattern = rf"def {endpoint}\("
    match = re.search(pattern, content)
    if match:
        print(f"  ✅ {endpoint} - 已实现")
    else:
        print(f"  ❌ {endpoint} - 未找到")

# 检查响应字段
fields_to_check = [
    ("content", '"content": ""'),
    ("truncated", '"truncated": False'),
    ("bytes", '"bytes": 0'),
    ("missing_file", '"missing_file"'),
]

print("\n检查响应字段：\n")
for field_name, field_pattern in fields_to_check:
    if field_pattern in content:
        print(f"  ✅ {field_name} 字段 - 已包含")
    else:
        print(f"  ❌ {field_name} 字段 - 未找到")

# 检查关键注释
key_comments = [
    "bytes 是实际返回内容的字节数",
    "从 DB 获取 truncated 标志",
    "聚合返回完整信息",
]

print("\n检查关键注释：\n")
for comment in key_comments:
    if comment in content:
        print(f"  ✅ 注释 '{comment}' - 已包含")
    else:
        print(f"  ❌ 注释 '{comment}' - 未找到")

# 检查 URL 路由
routes_to_check = [
    '/execs/{exec_id}/stdout',
    '/execs/{exec_id}/stderr',
    '/execs/{exec_id}/observation',
]

print("\n检查 API 路由：\n")
for route in routes_to_check:
    if route in content:
        print(f"  ✅ 路由 '{route}' - 已定义")
    else:
        print(f"  ❌ 路由 '{route}' - 未找到")

print("\n" + "="*60)
print("PR-1 实现验证完成！")
print("="*60)
