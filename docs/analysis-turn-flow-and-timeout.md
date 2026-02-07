# 为何没有「立刻任务开始 → 后台跑 → 结束后总结」的流程

## 预期 vs 现状

| 预期 | 现状 |
|------|------|
| 用户输入 → **立刻**回复「任务开始」 | 没有「立刻」的回复；要么等跑完才有一条，要么等 60s 超时才有兜底回复 |
| 后台跑 | 后台确实在跑（worker 执行 run_code_snippet） |
| 结束后回复「总结」 | 若在 60s 内跑完，会有一条「执行结果」；若超时，这条和「任务开始」混成一条超时提示 |
| 不串台、不重复、不乱序 | 已通过 client_turn_id 和 emit 去重缓解，但「任务开始」仍不是立刻的 |

## 根本原因（两点）

### 1. HTTP 请求是同步阻塞的

当前 reply_and_run + run_code_snippet 的调用链是：

```
用户发消息
  → POST /conversations/{id}/messages (create_message)
    → agent_decision.decide() 得到 reply_and_run
    → run_code_snippet_loop(...)
        → create_run() 创建 run
        → wait_run_done(run_id, max_wait_sec=60)  ← 在这里阻塞，最多 60 秒
        → 取 observation，再 decide，直到 reply 或 max_steps
    → 用 final_reply 拼成 assistant_content
    → 写一条 assistant 消息，commit
  → 返回 HTTP 200，body 里带 user_message + assistant_message
```

因此：

1. **整条 HTTP 请求要等 run 跑完或 60 秒超时后才返回**  
   - 跑完：客户端在「跑完后」才收到**一条**消息（执行结果）。  
   - 超时：请求在 60 秒后才结束，服务端返回「任务执行超时或异常…」这类兜底内容，客户端**此时**才收到。

2. **「任务开始」本质是「本次请求的响应」**  
   当前没有「先返回 200 + 任务开始，再在后台跑」的路径。  
   所以：
   - 若 run 很快完成：用户只会看到**一条**「执行结果」，不会先看到「任务开始」。  
   - 若 run 超过 60s：用户会在**约 60 秒后**才收到**一条**消息，内容是「好的，我将…」+ 超时注记——这就是你看到的「任务开始的提示在超时的 60 秒后发给用户」：**不是先发任务开始再超时，而是整次请求在 60 秒后超时，把这条兜底当成了“第一次/唯一一次”回复。**

3. **为何有时会先看到结果，再看到「超时」那条？**  
   - 可能 1：同一轮请求里 run 在 60s 内完成，先返回了「执行结果」；随后 2 秒拉消息或其它机制又拉到了**另一条**（例如旧逻辑下的重复消息或历史数据）。  
   - 可能 2：第一轮请求在 60s 后超时返回「超时」那条，第二轮请求很快返回「执行结果」；若前端未正确按 client_turn_id 丢弃过期响应，就会先显示第二轮的「结果」，再显示第一轮的「超时」提示，形成乱序。

### 2. 缺少「异步通知通道」：即使立刻返回，前端也要能拿到「结束后总结」

**光把 create_message 改成立刻返回还不够**：前端怎么拿到「结束后总结」那条消息？

必须满足其一：

- **前端轮询拉消息**：已有定时刷新（如 2s 拉一次 messages），worker 完成后把「总结」写入 DB，前端下次拉取就能看到。
- **SSE / WebSocket**：服务端在 run 完成时通过 push 通道推一条「总结」或「有新消息」通知，前端再拉或直接展示。

当前之所以能「看到完成消息」，是因为有 **emit_run_message**（或类似机制）在 run 完成时写入消息，且前端会刷新/拉取消息列表。两段式落地时**必须确认**：前端在任务结束后会刷新消息列表（或通过 push 触发拉取），否则用户只会永远看到「任务开始」，看不到「总结」。

---

## A) 补强：异步通知通道（落地检查清单）

两段式落地时务必确认：

1. **完成消息的写入**：worker 或后台编排在 run/loop 结束后，通过 **emit_run_message** 或等价逻辑把「总结」写入该 conversation 的一条新消息。
2. **前端的拉取**：  
   - 若仅轮询：当前已有「发消息后 2s 再拉一次 messages」及轮询 runs；要保证** run 完成后的某一时刻**前端会拉 messages（例如 runs 状态变为 succeeded 时触发一次拉取，或固定间隔拉 messages）。  
   - 若上 SSE/WS：run 完成时服务端 push，前端收到后拉 messages 或直接追加一条。
3. **验收**：发一条 run_code_snippet → 立刻看到「任务开始」→ 等 run 完成后，**不刷新页面**也能在对话流里看到「总结」（要么自动出现，要么点「刷新」后出现，取决于产品选择）。

---

## B) 修正：Start vs Done 区分，不能再用「同轮已回复」误杀完成消息

当前去重逻辑（run_messages.emit_run_message）是：

- **run_code_snippet** 时：若本对话里**已存在**某条 assistant 消息的 `meta.run_id` / `meta.run_ids` 包含本 run_id → **不再 emit**（避免「同一任务两条消息」）。

一旦改成两段式：

- **第一条** assistant 消息 = **task_start**（「任务开始」），meta 里会带 `run_ids_started`（或当前已有的 run_id/run_ids）。
- **第二条** 应由 **emit_run_message** 写入 = **task_done**（「总结」）。

若继续用「对话里已出现 run_id 就不 emit」的规则，会变成：**start 消息已经带了 run_id → emit 时认为「同轮已回复」→ 不再写 done 消息 → 用户永远没有「总结」。**

因此必须区分 **start** 和 **done**，不能混用一条泛化规则。

### 推荐规则

| 消息类型   | 谁写       | meta / source 约定 | 幂等 / 去重 |
|------------|------------|---------------------|-------------|
| task_start | create_message | 如 `meta.run_ids_started`，表示「本轮已启动的 run」 | 不涉及 emit |
| task_done  | emit_run_message | 如 `source_ref.kind = "run_done"`，`meta.run_id = run.id` | 只抑制「重复的 done」 |

**emit 侧**：

- **只**负责写 **task_done** 消息。
- **幂等判断**：查 DB 是否已存在 `source_ref.kind === "run_done"` 且 `source_ref.ref_id === run.id`（或 `meta.run_id === run.id`）；若已存在则不再写。
- **不要**再用「对话里任意消息的 meta 出现 run_id 就不 emit」这种泛化规则；那种规则会把 start 和 done 混在一起，误杀 done。

**create_message 侧**：

- task_start 消息的 meta 可记录 `run_ids_started`，仅用于展示/追溯，**不**用于 emit 的「是否写 done」判断。

---

## 相关代码位置

- **阻塞点（旧）**：`conversation_orchestrator.run_code_snippet_loop` 内 `wait_run_done(..., max_wait_sec=60)`。  
- **reply_and_run 分支**：`conversations._create_message` 中 `decision.decision == "reply_and_run"` 且 `run_type == "run_code_snippet"` 时创建 agent_loop_turn run、写 task_start、立即返回。  
- **两段式编排与护栏**：  
  - **RunStatus**：`app.db` 中 `RunStatus.WAITING_CHILD`。  
  - **yield-waiting-child**：`app.api.internal`，强幂等（已 waiting 且同 child → 204，不同 → 409）；设 `status=WAITING_CHILD` 并清空 `worker_id`/`lease_expires_at`。  
  - **orchestration-step**：同文件，WAIT_CHILD + step_index 匹配 → `action: "wait"`；超时（updated_at > 10min）→ `action: "reply"` 兜底。  
  - **wake**：`app.services.run_messages._wake_parent_run_if_waiting`，只清等待相关字段；`previous_output_json` 经 `_cap_previous_output_for_input` 做 size cap。  
  - **Worker 拉取**：`apps/agent-worker/worker/queue.py` 中 `fetch_runnable_candidate` 只拉 QUEUED/过期 RUNNING，queued 按 `created_at.asc()`。

## 若要实现「立刻任务开始 → 后台跑 → 结束后总结」

需要改成**异步两段式**，并满足 **A) 异步通道** 与 **B) Start/Done 区分**。

### 方案 1：create_message 立刻返回 + 现有 worker 跑 run，完成后 emit

1. **create_message 在 reply_and_run + run_code_snippet 时**  
   - 只做：创建 user 消息、创建 **一条** run（或只入队）、写**一条** assistant 消息（**task_start**），内容为「任务开始：xxx」，**立即返回 200**。  
   - **不**在本请求内调用 `run_code_snippet_loop` 或 `wait_run_done`。

2. **run 的执行与结果**  
   - 由现有 worker 拉 run、执行 run_code_snippet；run 完成后通过 **emit_run_message** 写**第二条**消息（**task_done**）。  
   - **emit 幂等**：按 B) 只按「是否已存在 task_done（source_ref.kind=run_done + ref_id=run.id）」判断，**不再**用「对话里已有 run_id 就不 emit」。

3. **前端**  
   - 轮次隔离（client_turn_id）保留。  
   - **必须**在任务结束后能拿到新消息：轮询拉 messages，或 run 完成后触发一次拉取，或 SSE/WS push 后拉取（见 A)）。

### 方案 2（推荐）：引入后台编排任务 `agent_loop_turn`

把「多步编排」从 create_message 挪到**后台任务**里跑，既不阻塞 HTTP，又复用现有 run_code_snippet_loop 逻辑：

1. **新任务类型**：**agent_loop_turn**  
   - 由 worker 拉取并执行。  
   - 任务内部：调用 core-api 的 agent_decision、create_run、wait_run_done（通过 DB/HTTP），执行现有的 **run_code_snippet_loop** 逻辑，直到结束。  
   - 最后写 **task_done** 消息（通过 core-api 的 emit 或等价接口）。

2. **create_message 在 reply_and_run + run_code_snippet 时**  
   - 只做：创建 user 消息、**创建一条 type=agent_loop_turn 的 run**（入队给 worker），写**一条** assistant 消息（**task_start**），**立即返回 200**。  
   - **不**在本请求内执行 run_code_snippet_loop。

3. **worker**  
   - 新增对 **agent_loop_turn** 的执行器：跑完 run_code_snippet_loop（或调用 core-api 的编排接口），结束时写 task_done 消息。

4. **emit_run_message**  
   - 只写 **task_done**；幂等只判断「是否已有同 run_id 的 run_done 消息」，不按「对话里是否出现过 run_id」抑制。

这样：用户发消息 → create_message 立刻返回 task_start → 后台 agent_loop_turn 跑编排 → 跑完后写 task_done → 前端通过轮询或 push 看到「总结」，且 start/done 不混、不误杀。

现有的 **run_code_snippet_loop**（max_steps clamp、previous_observation、wait_run_done、extract_reply/observation）逻辑保持不变；两段式后它**不在 create_message 里跑**，而是由「后台编排任务」调用（方案 2 的 agent_loop_turn 执行器）。

### 父 run 状态机 + 子 run 标准入队 + wake（收口方案）

为避免「worker 阻塞在 execute-orchestration 的 wait_run_done → 子 run 无人执行」的死锁，同时保持 Run/Worker 调度契约一致（不引入 RUNNING+worker_id 的非标准创建），采用**父 run 状态机、子 run 标准入队、子完成时唤醒父**：

- **core-api orchestration-step**：每次只返回下一步——`action: "reply"`（带 final_reply）、`action: "wait"`（防重放）或 `action: "create_run"`（带 run_request），不创建 run、不等待。
- **父 run 状态 WAITING_CHILD**：yield-waiting-child 将父 `status` 设为 **WAITING_CHILD**（不是 QUEUED），并清空 `worker_id`、`lease_expires_at`，使父**不可被 worker 拉取**；worker 只拉取 QUEUED（及过期 RUNNING），不拉 WAITING_CHILD。
- **worker 单步执行 agent_loop_turn**：从 `run.input_json` 读 `step_index`、`previous_output_json`、`run_ids`；调 orchestration-step。若 **reply**：返回 `{ ok: True, final_reply, run_ids }`，main 照常 `complete_success` + emit → task_done。若 **wait**：直接返回 `{ ok: True, yielded: True }`，不创建子 run、不再调 yield。若 **create_run**：用标准 **POST /runs** 创建子 run（QUEUED），再调 **POST /internal/runs/{parent_id}/yield-waiting-child**（body：child_run_id、step_index、run_ids），将父置为 WAITING_CHILD 并写 `output_json`（含 `waiting_child_run_id`、`waiting_step_index`）；worker 返回 `{ ok: True, yielded: True }`，main **不**调用 complete_success。
- **子 run 完成后唤醒父**：在 `emit_run_message` 中，当 run 带 `parent_run_id` 且为终态（SUCCEEDED/FAILED/CANCELED）时，先调用 `_wake_parent_run_if_waiting(db, run)`：仅当父 `output_json.state == "WAIT_CHILD"` 且 `waiting_child_run_id == run.id`（及 step_index 一致）时，合并 `step_index+1`、`previous_output_json`（见下 cap）、`run_ids` 到父的 `input_json`，**只清空** output_json 中的 `state`/`waiting_child_run_id`/`waiting_step_index` 等等待相关字段（保留其余 debug），将父 `status` 置为 QUEUED，使父再次被 worker 拉取并执行下一轮 orchestration-step。
- **Tasks 只显示顶层**：`_list_conversation_runs` 只返回 `parent_run_id == None` 的 run。
- **Chat 两条消息 source_ref**：task_start 固定为 `kind: "run_start"`, `ref_id: orchestration_run_id`；task_done 为 `kind: "run_done"`, `ref_id: run.id`。

### Worker 拉取顺序（FIFO）

- **fetch_runnable_candidate**：仅拉取 `status = QUEUED` 与「过期 RUNNING」；**不拉取 WAITING_CHILD**。
- 排序：queued 按 **created_at ASC**（FIFO），避免后创建的 child 先跑、父步进乱序。

### 护栏（防卡死 / 幽灵任务）

1. **yield-waiting-child 强幂等**  
   - 若父已 `status = WAITING_CHILD` 且已有 `waiting_child_run_id`：  
     - 本次 `child_run_id` **相同** → 204 no-op（不写库），HTTP 重试无副作用。  
     - 本次 **不同** → **409 Conflict**，避免覆盖成另一 child，导致父永远等不到「真正执行的 child」。

2. **wake 时谨慎清空 output_json**  
   - 只删除 `state`、`child_run_id`、`waiting_child_run_id`、`waiting_step_index`、`run_ids`，**不**把 `output_json` 整段置空，保留 run 的 debug 信息。  
   - 写入父 `input_json` 的 `previous_output_json` 做 **size cap**（如 4KB），只塞 observation 等预览，避免 input_json 越滚越大。

3. **parent 卡死自愈**  
   - **策略 A**：子 run 终态（SUCCEEDED/FAILED/CANCELED）都会触发 emit → `_wake_parent_run_if_waiting`，父不会被永久卡在 WAITING_CHILD。  
   - **策略 B 兜底**：若父处于 WAIT_CHILD 且 **updated_at 距当前超过 10 分钟**（如定时 job 将此类 run 置为 QUEUED 后被拉取），**orchestration-step** 返回 `action: "reply"`, `final_reply: "子任务超时/失败，请重试。"`，并清空该 run 的等待相关字段，由 worker 按正常 reply 完成 parent。  
   - 可选：定时任务将 `status = WAITING_CHILD` 且 `updated_at < now - 10min` 的 run 置为 QUEUED，以便上述兜底分支被触发。

### 验收用例（状态机闭环）

| 用例 | 要点 | 预期 |
|------|------|------|
| **1. 单步成功** | 一次执行即完成 | Tasks 仅 1 个顶层（agent_loop_turn）；Chat 两条（start → done）；DB 有 child 但列表过滤掉。 |
| **2. 多步修复** | 第一次必失败（如 1/0），第二次修复成功（1/1） | 2 个 child，不出现多个同时排队；parent 的 step_index 按 0→1→2 推进；Chat 仍 start + done。 |
| **3. 并发/重试幂等** | parent 已 WAITING_CHILD 时重复调 orchestration-step（或 yield 重试） | orchestration-step 返回 `action: "wait"`，worker 返回 yielded，不 create 新 child；yield 同 child_run_id → 204 no-op，不同 → 409；DB child 数量不增加。 |
| **4. child 失败 + 父继续** | child 直接报错（如 syntax error） | 子终态触发 emit → wake；父被唤醒并进入下一步 decision（reply 或再 run），不卡在 WAITING_CHILD。 |
