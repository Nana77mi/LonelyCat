"""
Agent Loop v2 集成测试
测试完整流程：run_code_snippet → OBSERVE → RESPOND
"""
import json
import os
from typing import Any

# 尝试导入 core-api 和 agent-worker
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    print("警告：httpx 未安装，跳过集成测试")


def test_run_code_with_output():
    """
    测试场景：执行代码并返回结果
    预期：output 包含 stdout
    """
    if not HTTPX_AVAILABLE:
        print("跳过：httpx 不可用")
        return

    core_api_url = os.getenv("CORE_API_URL", "http://localhost:8000")

    # 模拟创建 run_code_snippet 任务
    task_input = {
        "conversation_id": "test_conv_001",
        "language": "python",
        "code": "print(sum(i*i for i in range(100)))"
    }

    print("=" * 60)
    print("Agent Loop v2 集成测试")
    print("=" * 60)
    print(f"\n输入：{json.dumps(task_input, ensure_ascii=False, indent=2)}\n")

    try:
        # 1. 创建 Run（通过 agent-worker）
        with httpx.Client(timeout=60.0) as client:
            create_resp = client.post(
                f"{core_api_url}/internal/runs",
                json={
                    "type": "run_code_snippet",
                    "input_json": task_input,
                }
            )

            if create_resp.status_code != 200:
                print(f"❌ 创建 Run 失败：{create_resp.status_code}")
                print(create_resp.text)
                return

            run_data = create_resp.json()
            run_id = run_data.get("id")

            if not run_id:
                print("❌ Run ID 未返回")
                return

            print(f"✅ Run 已创建：{run_id}")
            print(f"状态：{run_data.get('status', 'PENDING')}")

            # 2. 等待 Run 完成（轮询）
            print("\n等待 Run 完成...")
            import time

            max_wait = 30  # 最多等待 30 秒
            start_time = time.time()

            while time.time() - start_time < max_wait:
                time.sleep(2)  # 每 2 秒轮询一次

                status_resp = client.get(
                    f"{core_api_url}/internal/runs/{run_id}"
                )

                if status_resp.status_code == 200:
                    status_data = status_resp.json()
                    status = status_data.get("status")

                    print(f"  状态：{status}")

                    if status in ("SUCCEEDED", "FAILED"):
                        print(f"\n✅ Run 完成（最终状态：{status}）")

                        # 3. 获取最终结果
                        result = status_data.get("output_json", {})

                        print("\n" + "=" * 60)
                        print("最终结果分析")
                        print("=" * 60)

                        # 显示 exec_id
                        exec_id = result.get("exec_id", "")
                        print(f"exec_id: {exec_id}")

                        # 显示 observation
                        observation = result.get("observation", {})
                        if observation:
                            print("\nObservation:")
                            print(f"  stdout_preview: {observation.get('stdout_preview', '')[:50]}...")
                            print(f"  stderr_preview: {observation.get('stderr_preview', '')[:50]}...")
                            print(f"  stdout_truncated: {observation.get('stdout_truncated', False)}")
                            print(f"  stderr_truncated: {observation.get('stderr_truncated', False)}")
                            print(f"  stdout_bytes: {observation.get('stdout_bytes', 0)}")
                            print(f"  stderr_bytes: {observation.get('stderr_bytes', 0)}")
                            print(f"  artifacts_count: {observation.get('artifacts_count', 0)}")

                        # 显示 reply（UI 会读取的字段）
                        reply = result.get("reply", "")
                        if reply:
                            print(f"\n✅ UI 显示的回复：\n{reply}\n")

                        # 验证预期结果
                        if "328350" in reply:
                            print("\n🎉 测试通过！stdout 已正确捕获并显示")
                        else:
                            print(f"\n⚠️  未在 reply 中找到预期结果 '328350'")

                        break

            print(f"\n⏱️ 等待超时（{max_wait}秒）")

    except httpx.TimeoutException as e:
        print(f"❌ 请求超时：{e}")
    except Exception as e:
        print(f"❌ 错误：{e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)


if __name__ == "__main__":
    test_run_code_with_output()
