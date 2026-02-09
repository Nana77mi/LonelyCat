# Reflection Analysis - Phase 2.3-C

## Overview

离线分析脚本，用于执行历史反思与 WriteGate 反馈信号分析。

## Features

### C1: 失败归因摘要 (Failure Attribution)

分析最近 N 次失败执行，生成摘要报告：

- **Top Error Steps**: 失败最多的步骤分布（validate, apply, verify, etc.）
- **Top Error Codes**: 最常见的错误代码分类
- **Average Failure Duration**: 平均失败耗时
- **Failure by Risk Level**: 按风险等级分布
- **Failure Details**: 前 20 条失败案例详情（含 artifact_path）

### C2: WriteGate 反馈信号 (WriteGate Feedback)

#### False Allow Detection

识别 `verdict=allow` 但 `status=failed/rolled_back` 的案例：

- **Total False Allow**: 误放行数量
- **False Allow Rate**: 误放行率（百分比）
- **Cases**: 详细案例列表（execution_id, plan_id, risk_level, error_step, error_message）

**用途**: 帮助发现 WriteGate 策略过于宽松的情况，需要收紧规则。

#### Potential False Deny Detection

识别 `verdict=deny` 的案例（MVP 版本需要人工审查）：

- **Total Deny**: 拒绝案例总数
- **Note**: 需要对比相似的 allow+completed 案例，判断是否过于保守

**用途**: 帮助发现 WriteGate 策略过于严格的情况，可能需要放宽规则。

## Usage

### Basic Usage

```bash
# 使用默认工作空间（仓库根目录）
python scripts/reflection_analysis.py

# 指定工作空间
python scripts/reflection_analysis.py --workspace /path/to/workspace

# 分析更多失败记录
python scripts/reflection_analysis.py --failed-limit 200
```

### Output to File

```bash
# 保存完整报告到 JSON 文件
python scripts/reflection_analysis.py --output report.json

# 查看报告
cat report.json | jq .
```

## Output Format

### Console Output (Summary)

```
================================================================================
LonelyCat Reflection Analysis Report
================================================================================

📊 Summary:
  Total Failed Executions: 42
  Total Allow Executions: 150
  Total Deny Executions: 8
  False Allow Rate: 12.5%

🔍 Failure Attribution:
  Average Failure Duration: 2.34s

  Top Error Steps:
    - validate: 15 occurrences
    - apply: 12 occurrences
    - verify: 10 occurrences
    - rollback: 5 occurrences

  Top Error Codes:
    - VALIDATION_ERROR: 15 occurrences
    - APPLY_ERROR: 12 occurrences
    - TEST_FAILURE: 8 occurrences
    - PERMISSION_ERROR: 7 occurrences

  Failure by Risk Level:
    - low: 10
    - medium: 20
    - high: 10
    - critical: 2

⚠️  WriteGate Feedback Signals:
  False Allow Cases: 19 / 150 (12.67%)

  Recent False Allow Cases:
    - exec_abc123 [medium] validate: [VALIDATION_ERROR] File not found...
    - exec_def456 [high] apply: [APPLY_ERROR] Permission denied...
    - exec_ghi789 [low] verify: Test failed: expected 5, got 3...

  Potential False Deny Cases: 8 (requires manual review)
    Note: MVP: False deny detection requires manual review. Compare deny cases with similar allow+completed patterns.

================================================================================
```

### JSON Output (Full Report)

```json
{
  "generated_at": "2024-01-15T10:30:00.000000+00:00",
  "workspace_root": "/path/to/workspace",
  "summary": {
    "total_failed": 42,
    "total_allow": 150,
    "total_deny": 8,
    "false_allow_rate": 12.67
  },
  "failure_attribution": {
    "total_failed": 42,
    "top_error_steps": [
      ["validate", 15],
      ["apply", 12],
      ["verify", 10],
      ["rollback", 5]
    ],
    "top_error_codes": [
      ["VALIDATION_ERROR", 15],
      ["APPLY_ERROR", 12],
      ["TEST_FAILURE", 8],
      ["PERMISSION_ERROR", 7]
    ],
    "avg_failure_duration": 2.34,
    "failure_by_risk_level": {
      "low": 10,
      "medium": 20,
      "high": 10,
      "critical": 2
    },
    "failures": [
      {
        "execution_id": "exec_abc123",
        "error_step": "validate",
        "error_message": "[VALIDATION_ERROR] File not found: src/main.py",
        "duration_seconds": 1.5,
        "risk_level": "medium",
        "artifact_path": ".lonelycat/executions/exec_abc123"
      }
    ]
  },
  "writegate_feedback": {
    "false_allow": {
      "total_allow": 150,
      "total_false_allow": 19,
      "false_allow_rate": 12.67,
      "cases": [
        {
          "execution_id": "exec_abc123",
          "plan_id": "plan_xyz",
          "risk_level": "medium",
          "error_step": "validate",
          "error_message": "[VALIDATION_ERROR] File not found"
        }
      ]
    },
    "potential_false_deny": {
      "total_deny": 8,
      "potential_false_deny_count": 0,
      "note": "MVP: False deny detection requires manual review...",
      "cases": [
        {
          "execution_id": "exec_deny_1",
          "plan_id": "plan_123",
          "risk_level": "critical",
          "verdict": "deny",
          "note": "Requires manual review - compare with similar allow+completed cases"
        }
      ]
    }
  }
}
```

## Exit Codes

- `0`: 分析成功完成
- `1`: 错误发生 或 False Allow Rate > 10% (警告)
- `2`: 配置错误（数据库不存在等）

## Use Cases

### 1. 每日失败报告

```bash
# 每日 cron job
python scripts/reflection_analysis.py --failed-limit 100 --output daily_report_$(date +%Y%m%d).json
```

### 2. 发版前检查

```bash
# 检查最近失败情况
python scripts/reflection_analysis.py --failed-limit 50

# 如果 False Allow Rate > 10%，会返回 exit code 1
if [ $? -eq 1 ]; then
    echo "⚠️ High false allow rate! Review WriteGate policies before release."
    exit 1
fi
```

### 3. WriteGate 策略调优

```bash
# 导出报告
python scripts/reflection_analysis.py --output report.json

# 分析 false allow 案例
cat report.json | jq '.writegate_feedback.false_allow.cases[]' | \
    jq -r '"\(.execution_id) [\(.risk_level)] \(.error_step): \(.error_message)"'

# 根据报告调整 WriteGate 策略
# 例如：如果 "validate" 步骤频繁失败，可能需要更严格的 pre-validation
```

### 4. 识别系统性问题

```bash
# 查看 Top Error Steps
cat report.json | jq '.failure_attribution.top_error_steps'

# 如果某个步骤失败率异常高，说明该步骤可能有系统性问题
# 例如：apply 步骤失败多 → 可能是权限配置问题
#       verify 步骤失败多 → 可能是测试不稳定
```

## Implementation Details

### Data Sources

- **Database**: `.lonelycat/executor.db` (SQLite)
- **Tables**: `executions` table
- **Filters**: `status IN ('failed', 'rolled_back')` for failure analysis

### Analysis Logic

#### Error Code Extraction

从 `error_message` 提取错误代码：

1. 如果消息包含 `[ERROR_CODE]` 格式，提取中括号内容
2. 否则，取第一个单词作为分类（截断至 30 字符）

#### False Allow Detection

简单但有效：

```sql
SELECT * FROM executions
WHERE verdict = 'allow'
  AND status IN ('failed', 'rolled_back')
```

#### False Deny Detection (MVP)

当前版本：只统计 deny 案例，标记为需要人工审查。

**未来增强**（Phase 3.x）：
- 分析 ChangePlan 相似度（affected_paths, risk_level, file types）
- 对比历史 allow+completed 案例
- 使用 LLM 判断是否过于保守

### Performance

- **Database Query**: 使用索引，性能良好（< 1s for 100K records）
- **Memory**: 内存占用低（只加载摘要数据，不加载完整 artifact）
- **Scalability**: 支持分页查询，可扩展至百万级记录

## Testing

```bash
# 运行测试
python -m pytest scripts/tests/test_reflection_analysis.py -v

# 8 个测试覆盖：
# 1. Database query functions
# 2. Failure attribution analysis
# 3. False allow detection
# 4. False deny detection
# 5. Full report generation
# 6. Empty database handling
```

## Limitations (MVP)

1. **False Deny Detection**: 需要人工审查，无自动相似度分析
2. **Error Code Extraction**: 简单规则，可能不准确
3. **Time-based Analysis**: 不支持按时间段分析（例如：最近 24h/7d）
4. **Trend Analysis**: 不支持趋势分析（失败率是否上升）

## Future Enhancements (Phase 3.x)

1. **Advanced False Deny**: LLM-powered similarity analysis
2. **Time Series**: 按时间段分析失败趋势
3. **Root Cause Analysis**: 自动归因根因（例如：环境问题 vs 代码问题）
4. **Recommendation**: 自动生成策略调优建议
5. **Web UI**: 集成到 Web Console，交互式分析

## See Also

- `scripts/prod_validation.py` - 生产验证脚本
- `apps/core-api/app/api/executions.py` - Execution History API
- `docs/PHASE_2_3_C_COMPLETION.md` - 完整实现文档

---

**Phase**: 2.3-C (Reflection MVP)
**Status**: ✅ Complete
**Next**: 2.3-D (工程化收口)
