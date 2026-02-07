"""追加 PR-1 测试用例到 test_sandbox_api.py"""
import sys

# 读取原测试文件
with open(r"d:\Project\lonelycat\LonelyCat\apps\core-api\tests\test_sandbox_api.py", "r", encoding="utf-8") as f:
    original_content = f.read()

# 读取要追加的内容
with open(r"d:\Project\lonelycat\LonelyCat\apps\core-api\tests\test_sandbox_api_pr1_append.txt", "r", encoding="utf-8") as f:
    append_content = f.read().lstrip('\n\r')

# 追加并保存
with open(r"d:\Project\lonelycat\LonelyCat\apps\core-api\tests\test_sandbox_api.py", "w", encoding="utf-8") as f:
    f.write(original_content.rstrip() + "\n\n")
    f.write(append_content)

print("✅ 测试用例已追加到 test_sandbox_api.py")
