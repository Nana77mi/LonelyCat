"""
LonelyCat Reflection Analysis - Phase 2.3-C

离线分析脚本，用于：
1. 失败归因摘要（Top error_step, error_code, 失败耗时分析）
2. WriteGate 反馈信号（false allow/deny 检测）

Usage:
    python scripts/reflection_analysis.py --workspace /path/to/workspace
    python scripts/reflection_analysis.py --workspace /path/to/workspace --failed-limit 50
    python scripts/reflection_analysis.py --workspace /path/to/workspace --output report.json
"""

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import Counter, defaultdict
from datetime import datetime, timezone


# ==================== Data Models ====================

class FailedExecution:
    """失败执行的简化模型"""
    def __init__(
        self,
        execution_id: str,
        plan_id: str,
        changeset_id: str,
        status: str,
        verdict: str,
        risk_level: str,
        started_at: str,
        ended_at: Optional[str],
        duration_seconds: Optional[float],
        files_changed: int,
        error_step: Optional[str],
        error_message: Optional[str],
        artifact_path: Optional[str],
    ):
        self.execution_id = execution_id
        self.plan_id = plan_id
        self.changeset_id = changeset_id
        self.status = status
        self.verdict = verdict
        self.risk_level = risk_level
        self.started_at = started_at
        self.ended_at = ended_at
        self.duration_seconds = duration_seconds
        self.files_changed = files_changed
        self.error_step = error_step
        self.error_message = error_message
        self.artifact_path = artifact_path


# ==================== Database Query ====================

def get_failed_executions(
    db_path: Path, limit: int = 100
) -> List[FailedExecution]:
    """
    从 SQLite 获取失败的执行记录

    Args:
        db_path: executor.db 路径
        limit: 最大返回数量

    Returns:
        失败执行列表
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT
            execution_id,
            plan_id,
            changeset_id,
            status,
            verdict,
            risk_level,
            started_at,
            ended_at,
            duration_seconds,
            files_changed,
            verification_passed,
            health_checks_passed,
            rolled_back,
            error_step,
            error_message,
            artifact_path
        FROM executions
        WHERE status IN ('failed', 'rolled_back')
        ORDER BY started_at DESC
        LIMIT ?
    """

    cursor.execute(query, (limit,))
    rows = cursor.fetchall()
    conn.close()

    executions = []
    for row in rows:
        executions.append(
            FailedExecution(
                execution_id=row["execution_id"],
                plan_id=row["plan_id"],
                changeset_id=row["changeset_id"],
                status=row["status"],
                verdict=row["verdict"],
                risk_level=row["risk_level"] or "unknown",
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                duration_seconds=row["duration_seconds"],
                files_changed=row["files_changed"],
                error_step=row["error_step"],
                error_message=row["error_message"],
                artifact_path=row["artifact_path"],
            )
        )

    return executions


def get_allow_executions(db_path: Path, limit: int = 500) -> List[Dict[str, Any]]:
    """获取 verdict=allow 的执行记录"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT
            execution_id,
            plan_id,
            status,
            verdict,
            risk_level,
            started_at,
            error_step,
            error_message
        FROM executions
        WHERE verdict = 'allow'
        ORDER BY started_at DESC
        LIMIT ?
    """

    cursor.execute(query, (limit,))
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_deny_executions(db_path: Path, limit: int = 100) -> List[Dict[str, Any]]:
    """获取 verdict=deny/need_approval 的执行记录"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT
            execution_id,
            plan_id,
            status,
            verdict,
            risk_level,
            started_at
        FROM executions
        WHERE verdict IN ('deny', 'need_approval')
        ORDER BY started_at DESC
        LIMIT ?
    """

    cursor.execute(query, (limit,))
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


# ==================== C1: 失败归因摘要 ====================

def analyze_failure_attribution(
    executions: List[FailedExecution],
) -> Dict[str, Any]:
    """
    分析失败归因

    Returns:
        {
            "total_failed": int,
            "top_error_steps": [(step, count), ...],
            "top_error_codes": [(code, count), ...],
            "avg_failure_duration": float,
            "failure_by_risk_level": {risk: count},
            "failures": [
                {
                    "execution_id": str,
                    "error_step": str,
                    "error_message": str,
                    "duration_seconds": float,
                    "artifact_path": str
                }
            ]
        }
    """
    if not executions:
        return {
            "total_failed": 0,
            "top_error_steps": [],
            "top_error_codes": [],
            "avg_failure_duration": 0.0,
            "failure_by_risk_level": {},
            "failures": [],
        }

    # Top error_step 分布
    error_steps = [e.error_step for e in executions if e.error_step]
    step_counter = Counter(error_steps)
    top_error_steps = step_counter.most_common(10)

    # Top error_code（从 error_message 提取）
    error_codes = []
    for e in executions:
        if e.error_message:
            # 简单提取：假设 error_code 在 [] 中，例如 "[VALIDATION_ERROR]"
            if "[" in e.error_message and "]" in e.error_message:
                start = e.error_message.index("[")
                end = e.error_message.index("]")
                code = e.error_message[start + 1 : end]
                error_codes.append(code)
            else:
                # 否则取第一个单词作为分类
                words = e.error_message.split()
                if words:
                    error_codes.append(words[0][:30])  # 限制长度

    code_counter = Counter(error_codes)
    top_error_codes = code_counter.most_common(10)

    # 平均失败耗时
    durations = [e.duration_seconds for e in executions if e.duration_seconds is not None]
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    # 按 risk_level 分布
    risk_levels = [e.risk_level for e in executions]
    risk_counter = Counter(risk_levels)
    failure_by_risk = dict(risk_counter)

    # 失败列表（前 20 条详细信息）
    failures = []
    for e in executions[:20]:
        failures.append(
            {
                "execution_id": e.execution_id,
                "error_step": e.error_step or "unknown",
                "error_message": (e.error_message or "")[:200],  # 截断长消息
                "duration_seconds": e.duration_seconds,
                "risk_level": e.risk_level,
                "artifact_path": e.artifact_path or "N/A",
            }
        )

    return {
        "total_failed": len(executions),
        "top_error_steps": top_error_steps,
        "top_error_codes": top_error_codes,
        "avg_failure_duration": round(avg_duration, 2),
        "failure_by_risk_level": failure_by_risk,
        "failures": failures,
    }


# ==================== C2: WriteGate 反馈信号 ====================

def analyze_false_allow(
    allow_executions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    分析 False Allow：verdict=allow 但 status=failed

    Returns:
        {
            "total_false_allow": int,
            "false_allow_rate": float,
            "cases": [
                {
                    "execution_id": str,
                    "plan_id": str,
                    "risk_level": str,
                    "error_step": str,
                    "error_message": str
                }
            ]
        }
    """
    false_allows = [e for e in allow_executions if e["status"] in ("failed", "rolled_back")]

    cases = []
    for e in false_allows[:20]:  # 最多返回 20 条
        cases.append(
            {
                "execution_id": e["execution_id"],
                "plan_id": e["plan_id"],
                "risk_level": e["risk_level"] or "unknown",
                "error_step": e["error_step"] or "unknown",
                "error_message": (e["error_message"] or "")[:200],
            }
        )

    total_allow = len(allow_executions)
    false_allow_count = len(false_allows)
    false_allow_rate = (false_allow_count / total_allow * 100) if total_allow > 0 else 0.0

    return {
        "total_allow": total_allow,
        "total_false_allow": false_allow_count,
        "false_allow_rate": round(false_allow_rate, 2),
        "cases": cases,
    }


def analyze_potential_false_deny(
    deny_executions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    分析潜在 False Deny：verdict=deny 但相似低风险变更历史都成功

    注意：这是一个简化版本，真正的实现需要：
    1. 分析 ChangePlan 的相似度（affected_paths, risk_level）
    2. 查询历史执行中相似的 allow + completed 案例
    3. 对比 deny 案例是否过于保守

    MVP 版本：只统计 deny 案例，标记为"需要人工审查"

    Returns:
        {
            "total_deny": int,
            "potential_false_deny_count": int,
            "note": str,
            "cases": [
                {
                    "execution_id": str,
                    "plan_id": str,
                    "risk_level": str,
                    "verdict": str
                }
            ]
        }
    """
    # MVP: 只返回 deny 案例，标记为需要人工审查
    cases = []
    for e in deny_executions[:20]:
        cases.append(
            {
                "execution_id": e["execution_id"],
                "plan_id": e["plan_id"],
                "risk_level": e["risk_level"] or "unknown",
                "verdict": e["verdict"],
                "note": "Requires manual review - compare with similar allow+completed cases",
            }
        )

    return {
        "total_deny": len(deny_executions),
        "potential_false_deny_count": 0,  # MVP: 需要人工分析
        "note": "MVP: False deny detection requires manual review. Compare deny cases with similar allow+completed patterns.",
        "cases": cases,
    }


# ==================== Main ====================

def generate_reflection_report(
    workspace_root: Path, failed_limit: int = 100
) -> Dict[str, Any]:
    """
    生成完整的反思分析报告

    Args:
        workspace_root: 工作空间根目录
        failed_limit: 最大失败记录数

    Returns:
        完整报告字典
    """
    db_path = workspace_root / ".lonelycat" / "executor.db"

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    print(f"[Reflection] Loading data from {db_path}...")

    # 1. 获取失败执行
    failed_executions = get_failed_executions(db_path, limit=failed_limit)
    print(f"[Reflection] Found {len(failed_executions)} failed executions")

    # 2. 获取 allow 执行
    allow_executions = get_allow_executions(db_path, limit=500)
    print(f"[Reflection] Found {len(allow_executions)} allow executions")

    # 3. 获取 deny 执行
    deny_executions = get_deny_executions(db_path, limit=100)
    print(f"[Reflection] Found {len(deny_executions)} deny executions")

    # C1: 失败归因分析
    print("[Reflection] Analyzing failure attribution...")
    failure_analysis = analyze_failure_attribution(failed_executions)

    # C2: False Allow 分析
    print("[Reflection] Analyzing false allow cases...")
    false_allow_analysis = analyze_false_allow(allow_executions)

    # C2: 潜在 False Deny 分析
    print("[Reflection] Analyzing potential false deny cases...")
    false_deny_analysis = analyze_potential_false_deny(deny_executions)

    # 组装完整报告
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace_root": str(workspace_root),
        "summary": {
            "total_failed": failure_analysis["total_failed"],
            "total_allow": false_allow_analysis["total_allow"],
            "total_deny": false_deny_analysis["total_deny"],
            "false_allow_rate": false_allow_analysis["false_allow_rate"],
        },
        "failure_attribution": failure_analysis,
        "writegate_feedback": {
            "false_allow": false_allow_analysis,
            "potential_false_deny": false_deny_analysis,
        },
    }

    return report


def print_report_summary(report: Dict[str, Any]) -> None:
    """打印报告摘要到控制台"""
    print("\n" + "=" * 80)
    print("LonelyCat Reflection Analysis Report")
    print("=" * 80)

    summary = report["summary"]
    print(f"\n📊 Summary:")
    print(f"  Total Failed Executions: {summary['total_failed']}")
    print(f"  Total Allow Executions: {summary['total_allow']}")
    print(f"  Total Deny Executions: {summary['total_deny']}")
    print(f"  False Allow Rate: {summary['false_allow_rate']}%")

    # Failure Attribution
    print(f"\n🔍 Failure Attribution:")
    failure = report["failure_attribution"]
    print(f"  Average Failure Duration: {failure['avg_failure_duration']}s")

    print(f"\n  Top Error Steps:")
    for step, count in failure["top_error_steps"][:5]:
        print(f"    - {step}: {count} occurrences")

    print(f"\n  Top Error Codes:")
    for code, count in failure["top_error_codes"][:5]:
        print(f"    - {code}: {count} occurrences")

    print(f"\n  Failure by Risk Level:")
    for risk, count in failure["failure_by_risk_level"].items():
        print(f"    - {risk}: {count}")

    # WriteGate Feedback
    print(f"\n⚠️  WriteGate Feedback Signals:")
    false_allow = report["writegate_feedback"]["false_allow"]
    print(f"  False Allow Cases: {false_allow['total_false_allow']} / {false_allow['total_allow']} ({false_allow['false_allow_rate']}%)")

    if false_allow["cases"]:
        print(f"\n  Recent False Allow Cases:")
        for case in false_allow["cases"][:3]:
            print(f"    - {case['execution_id']} [{case['risk_level']}] {case['error_step']}: {case['error_message'][:60]}...")

    false_deny = report["writegate_feedback"]["potential_false_deny"]
    print(f"\n  Potential False Deny Cases: {false_deny['total_deny']} (requires manual review)")
    print(f"    Note: {false_deny['note']}")

    print("\n" + "=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description="LonelyCat Reflection Analysis - Failure Attribution & WriteGate Feedback"
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(__file__).parent.parent,
        help="Workspace root directory (default: repo root)",
    )
    parser.add_argument(
        "--failed-limit",
        type=int,
        default=100,
        help="Maximum number of failed executions to analyze (default: 100)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON file path (optional)",
    )

    args = parser.parse_args()

    try:
        # 生成报告
        report = generate_reflection_report(args.workspace, args.failed_limit)

        # 打印摘要
        print_report_summary(report)

        # 保存到文件
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\n✅ Full report saved to: {args.output}")
        else:
            print("\n💡 Tip: Use --output report.json to save full report to file")

        # 返回状态码
        if report["summary"]["false_allow_rate"] > 10.0:
            print("\n⚠️  WARNING: High false allow rate (>10%). Review WriteGate policies!")
            return 1

        print("\n✅ Reflection analysis complete")
        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
