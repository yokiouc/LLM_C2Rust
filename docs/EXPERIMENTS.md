## 实验评估（第16轮：论文表格导出）

目标：用现有数据库里的 run/steps/metrics 数据，导出一张可以直接放进论文第四章的 CSV 表格，用来对比 baseline 与 enhanced 两组。

### baseline 与 enhanced 的定义（写论文用）

- baseline：只做“编译/测试验证”，不做检索增强，不做补丁生成与应用。
- enhanced：在 baseline 基础上，运行完整闭环：检索 → 生成补丁 → 应用 → 编译/测试 → 诊断 → 记录指标（有限轮次）。

### 怎么跑 baseline / enhanced（最小流程）

1) baseline（只验证，不修复）

```json
POST /agent/run
{
  "snapshot_id": 1,
  "workspace_path": "F:/path/to/workspace",
  "task_description": "baseline run",
  "mode": "baseline",
  "cmd": ["cargo", "test"],
  "timeout": 60,
  "env": {"RUNNER_MODE": "mock", "MOCK_SCENARIO": "compile_fail"}
}
```

2) enhanced（闭环修复，有限轮次）

```json
POST /agent/run
{
  "snapshot_id": 1,
  "workspace_path": "F:/path/to/workspace",
  "task_description": "E0502 cannot borrow x",
  "mode": "enhanced",
  "max_iters": 2,
  "no_progress_limit": 1,
  "filters": {"kind": ["rust_function_slice", "replacement_strategy", "interface_constraint", "behavior_constraint"]},
  "top_k": 10,
  "patch_backend": "template_edit",
  "retrieval_model_id": "stub-1536",
  "cmd": ["cargo", "test"],
  "timeout": 60,
  "env": {"RUNNER_MODE": "mock", "MOCK_SCENARIO": "compile_fail"}
}
```

### 导出论文表格（CSV）

设置数据库连接：

- `DATABASE_URL` 或 `POSTGRES_DSN`

运行导出脚本：

```bash
python scripts/export_experiments_csv.py --out experiments.csv
```

可选：只导出指定 run_id：

```bash
python scripts/export_experiments_csv.py --out experiments.csv --run-id <run_id1> --run-id <run_id2>
```

### CSV 列解释（论文友好）

- `project/snapshot/commit`：项目与快照标识
- `mode`：baseline 或 enhanced
- 正确性：`compile_ok`、`test_ok`、`final_status`、`diagnose_issue_count`
- 安全性（轻量统计）：`unsafe_blocks`、`raw_ptr_count`、`unsafe_api_count`
- 代价/开销：`iteration_count`、`patch_rounds`、`rollback_count`、`total_ms/retrieve_ms/generate_ms/execute_ms`
- 失败解释：`primary_error_kind`、`final_stop_reason`

注意：安全性指标目前用“朴素字符串统计”近似（本科口径），用于小规模实验与趋势展示。

