## PR6: 新增任务 run_code_snippet（L2）

### 功能
- **run_code_snippet** 任务：input 为 `language`（python | shell）+ `code`/`script`，通过 `skill.python.run` / `skill.shell.run` 执行，收集 stdout/stderr/artifacts，失败可回放。
- **Runner**：`execute` 增加 `run_code_snippet` 分支，`_handle_run_code_snippet` 校验 `conversation_id`（必填）、`language`、`code`/`script`，可选 `settings_snapshot`、`timeout_ms`；使用 `run_task_with_steps` 输出 task_result_v0（version/task_type/trace_id/steps/artifacts）。
- **core-api**：`DEFAULT_ALLOWED_RUN_TYPES` 增加 `run_code_snippet`。

### 测试（TDD）
- `test_runner_run_code_snippet.py`：python 输出含 exec_id/exit_code/status、steps 含 tool.skill.python.run；shell 调用 skill.shell.run；缺 conversation_id 抛 ValueError；execute 派发 run_code_snippet 返回含 ok 的 result。
- `test_task_output_schema.py`：`run_code_snippet` 加入 ALLOWED_RUN_TYPES 与 covered，新增 `test_run_code_snippet_output_has_schema` 断言 task_result_v0 schema。

### 相关
- PHASE2 2.3 验收：run_code_snippet 任务（本 PR 通过 SkillsProvider 的 python.run/shell.run 实现，sandbox 容器化可后续接同一任务类型）。
