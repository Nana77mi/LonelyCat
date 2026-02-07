# TaskResult v0 Spec

本规范定义 agent-worker 任务执行写入 Run.output_json 的统一结构（TaskResult v0），用于：

- **可观测**：失败也能看到执行到哪一步、耗时、错误码、trace
- **可回放/比对**：和 Run.input_json.trace_id、facts_snapshot_id 串起来
- **可扩展**：后续加入更多 task 类型（research/doc_edit/sandbox）不发散
- **UI 统一展示**：RunsPanel/RunDetailsDrawer 不需要按 task type 写特例

**约束**：v0 阶段不强制新增数据库表，结构落在 Run.output_json（必要时同时在 input_json 写少量元信息）。

---

## 1. 版本与兼容

### 1.1 版本字段

- **version**: 固定为 `"task_result_v0"`（字符串）

### 1.2 兼容策略

- **生产者（agent-worker）**：必须写出 version、ok、trace_id、steps、artifacts（至少为空对象/空数组）。
- **消费者（core-api/UI）**：必须容忍缺字段（老数据），用默认值兜底。

---

## 2. 顶层结构（Run.output_json）

```json
{
  "version": "task_result_v0",
  "ok": true,
  "trace_id": "32-hex",
  "facts_snapshot_id": "64-hex-or-null",
  "facts_snapshot_source": "input_json|computed|null",
  "task_type": "summarize_conversation",
  "result": {},
  "artifacts": {},
  "steps": [],
  "trace_lines": [],
  "error": null
}
```

### 2.1 字段说明（必填/可选）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| version | string | ✅ | 固定 "task_result_v0" |
| ok | boolean | ✅ | 任务业务是否成功（与 RunStatus 对齐，但更细：失败也必须返回完整结构） |
| trace_id | string | ✅ | 32 位小写 hex。必须与 Run.input_json.trace_id 一致（若 input 没有则 worker 生成并在 output 写出） |
| facts_snapshot_id | string\|null | ✅ | 64 位小写 hex；无 facts 时可为 null |
| facts_snapshot_source | "input_json"\|"computed"\|null | ✅ | snapshot 来源：使用 input 预写 / worker 自算 / 无 |
| task_type | string | ✅ | 当前 run 的类型（例如 "summarize_conversation"），便于 UI 直接展示 |
| result | object | ✅ | 任务的“语义结果”（task-specific），用于程序化消费；可为空对象 |
| artifacts | object | ✅ | 任务产物（可展示/可下载/可追溯），按类型组织；可为空对象 |
| steps | array | ✅ | 执行步骤记录（见第 3 节）；可为空数组（不推荐） |
| trace_lines | array\<string\> | ✅ | worker trace 输出行（用于排查）。可为空数组 |
| error | object\|null | ✅ | 顶层错误摘要（见第 4 节）；成功时为 null |

---

## 3. Steps v0

### 3.1 Step 结构

```json
{
  "name": "llm_generate",
  "ok": true,
  "duration_ms": 123,
  "error_code": null,
  "meta": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | ✅ | 步骤名（短、稳定、snake_case） |
| ok | boolean | ✅ | 步骤是否成功 |
| duration_ms | integer | ✅ | 毫秒耗时，>= 0 |
| error_code | string\|null | ✅ | 失败时的错误码（建议为 Exception.__name__ 或自定义枚举） |
| meta | object | ✅ | 结构化摘要（必须脱敏、限制大小）；可为空对象 |

### 3.2 Steps 命名建议（summarize_conversation 模板）

- fetch_messages
- fetch_facts
- build_prompt
- llm_generate
- （可选）persist_output

### 3.3 Steps 命名建议（run_code_snippet 模板，Agent Loop v2）

- tool_call: 调用工具（如 skill.python.run）
- observation: 读取执行结果（stdout/stderr/artifacts）
- respond: 生成最终回复（基于 observation）

**observation step 的 meta 字段（Agent Loop v2）**：

```json
{
  "exec_id": "e_xxx",
  "exit_code": 0,
  "stdout_preview": "前 200 字节",
  "stderr_preview": "前 200 字节",
  "stdout_truncated": false,
  "stderr_truncated": false,
  "stdout_bytes": 1234,
  "stderr_bytes": 56,
  "artifacts_count": 3
}
```

**respond step 的 meta 字段（Agent Loop v2）**：

```json
{
  "response_type": "direct",
  "response_preview": "前 200 字节",
  "exec_id": "e_xxx"
}
```

### 3.4 Steps 约束

- duration_ms 必须使用单调时钟计算（time.monotonic() / perf_counter()），避免负数。
- 任意步骤失败：
  - steps[i].ok=false
  - steps[i].error_code 非空
  - 顶层 ok=false
  - error 必须给出摘要（见第 4 节）
- v0 阶段允许“尽力记录”：即使失败也要把已经完成的 steps 写入。

---

## 4. Error v0（顶层错误摘要）

```json
{
  "code": "LLMError",
  "message": "Generation failed",
  "retryable": false,
  "step": "llm_generate"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| code | string | ✅ | 错误类型/枚举（如 LLMError、MemoryUnavailable） |
| message | string | ✅ | 短消息（避免敏感信息） |
| retryable | boolean | ✅ | 是否可重试 |
| step | string | ✅ | 首个失败 step 的 name |

v0 建议：code 可先用 Exception.__name__，后续再归一化。

---

## 5. Artifacts v0

Artifacts 用于 UI 展示与长期扩展。按类别组织，字段稳定、避免 task-specific 混乱。

### 5.1 summarize_conversation 最小 artifacts

```json
{
  "summary": { "text": "...", "format": "markdown" },
  "facts": { "snapshot_id": "64hex", "source": "input_json" }
}
```

| artifact | 字段 | 说明 |
|----------|------|------|
| summary | text, format | format: "markdown" / "text" |
| facts | snapshot_id, source | 与顶层 snapshot 对齐；source 同 facts_snapshot_source |

### 5.2 artifacts 通用约束

- 不允许在 artifacts 中存放敏感 secrets。
- 单个字符串字段建议截断（例如 32KB）避免 UI 卡死。
- 如需存放大内容（HTML、PDF、日志文件），v0 建议先只存摘要；后续 v1 再引入 artifact 存储（文件/表）。

---

## 6. 与 Run.input_json 的关系

### 6.1 必要 input 字段（建议）

- **trace_id**: 32-hex（core-api 注入，worker 复用）
- **facts_snapshot_id**: 64-hex（core-api 在 store 可用时预写；worker 可复用）

### 6.2 一致性规则（强烈建议测试锁定）

- 若 input_json.trace_id 合法，则 output_json.trace_id 必须相同
- 若 input_json.facts_snapshot_id 合法且 worker 使用该值，则：
  - output_json.facts_snapshot_id 相同
  - facts_snapshot_source == "input_json"
- 否则：
  - worker 计算 snapshot 并写出
  - facts_snapshot_source == "computed"

---

## 7. 最小验收（Definition of Done）

对 **summarize_conversation**：

**成功时：**

- version/task_type/ok/trace_id/steps/artifacts/trace_lines 均存在
- artifacts.summary.text 可在 UI 展示

**失败时（mock LLM throw）：**

- ok=false
- steps 中 llm_generate.ok=false 且 error_code 非空
- error 非空（含 code/message/retryable/step）
- RunStatus=FAILED 且 output_json 仍完整保存

---

## 8. 未来扩展（v1+ 方向，不属于 v0 必做）

- **task_state**: 引入 WAIT_CONFIRM/PAUSED（配合 L1/L2 工具）
- **artifacts 外置存储**：artifact 表或对象存储
- **step_events 流式落库**：用于实时进度条/日志
- **cost 字段**：token、工具调用次数、时间预算等
