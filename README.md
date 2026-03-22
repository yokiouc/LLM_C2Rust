# 1. 项目简介

这个仓库是一个本科毕设原型：用于改进 **C2Rust 迁移后得到的 Rust 基线代码**的“可修复性、可验证性与可追踪性”。

需要强调两点：

- **C2Rust 是基线迁移工具**：它负责把 C 项目转成可编译的 Rust workspace（baseline）。
- **本项目不是重写 C2Rust**：本项目做的是迁移后的后处理强化，包括证据库/检索增强、受控补丁生成、最小 Repair Agent 闭环，以及 baseline vs enhanced 的小规模实验导出。

# 2. 项目定位与贡献边界

## Baseline tool（外部工具负责的部分）

- **C2Rust**：把 C 代码转译为 Rust baseline workspace（本项目只调用它、摄取其输出，不改造它的内部）。
- **Rust/Cargo**：真实编译与测试工具链（本项目也支持 mock runner，用于在不装 Rust 的情况下稳定演示闭环）。

## This project’s contribution（本项目实现的重点）

- **证据库与检索增强**：把代码切片与多类证据（规则、策略、约束等）入库；支持混合检索并组织 Evidence Pack。
- **受控补丁生成**：把 Evidence Pack + 目标函数/边界/约束组织成受控输入，生成 unified diff 补丁。
- **补丁应用与回滚**：把补丁应用到 workspace，失败或无进展时回滚，并留下可追踪记录。
- **Repair Agent 闭环（最小多轮）**：按状态机执行 “检索→生成→应用→验证→诊断→停止/回滚”，并记录每一步的输入输出与耗时。
- **baseline vs enhanced 实验**：同一项目两种模式跑通后，导出 experiments.csv 用于论文表格。

# 3. 系统架构图与主流程
系统架构图：

下面是一次 enhanced 运行的主链路（文字版流程图）：

```
workspace/snapshot
  → 检索证据（hybrid retrieve）
  → 组织 Evidence Pack（包含规则/策略/约束/代码切片等）
  → 生成受控补丁（unified diff，受边界/约束限制）
  → 应用补丁（apply）
  → 执行 build/test（runner：mock 或 real）
  → 诊断错误（diagnose）
  → 回滚或停止（no_progress / apply_fail / success 等）
  → 记录 steps / patches / metrics / summary（可复现导出）
```

baseline 模式是同一套框架的对照组：它**只做 build/test 验证与诊断记录**，不做检索与补丁。

# 4. 当前已实现的主要模块

## 证据库与检索

- 用 PostgreSQL + pgvector 存储代码切片与证据文本，并保存 embedding。
- 支持混合检索（词法检索 + 向量检索 + 融合排序），输出可直接给补丁生成使用的 Evidence Pack。
- 证据条目携带 meta 标签（evidence_type、risk_tags、constraint_tags、api_tags 等），便于展示与实验解释。

## 补丁生成与应用

- 生成受控补丁：输入为 Evidence Pack 与目标函数/边界/约束，输出为 unified diff。
- 应用补丁到 workspace，并在必要时回滚；每次补丁会落库并关联 run_id，便于追踪。
- demo/pilot 默认使用模板型 provider（template_edit）来保证流程稳定可演示。

## Runner / Diagnose

- Runner 支持两种运行方式：
  - mock：用固定夹具模拟 success/compile_fail/test_fail/timeout，便于稳定演示与对比实验。
  - real：调用 cargo（需要本机 Rust 工具链）。
- Diagnose 会对 stderr/log 做轻量解析，输出结构化 issues，用于失败解释与 stop_reason。

## Agent / FSM

- /agent/run 触发一次运行，内部按状态机执行并写入数据库：
  - steps：每一步的 input/output/耗时/是否成功
  - patches：每次补丁的 diff、状态、错误信息
  - metrics：模式、轮次、耗时、停止原因、主要错误类型等
- /runs/{id} 可查看一次运行的完整记录与 summary（用于答辩截图）。

## Demo

- scripts/run_demo.py 会自动创建一个极小 workspace + 快照 + 证据，并跑一次 enhanced 闭环，输出关键信息。

## Pilot 实验

- scripts/run_pilots.py 会准备两个小 workspace，并对每个 workspace 跑 baseline 与 enhanced，最后导出 experiments.csv。
- pilot 的目标是“小规模、可复现、可写论文”，不是工业级 benchmark。

## CSV 导出

- scripts/export_experiments_csv.py 从数据库汇总 runs/metrics/patches，并扫描 workspace 做轻量安全性统计，导出 experiments.csv。

# 5. 运行环境与依赖

最小运行前提（建议按下面顺序准备）：

- Python（项目主要为 Python 服务）
- PostgreSQL + pgvector（推荐用 Docker 启动数据库容器）
- Docker（主要用于数据库；API 推荐本机启动）

可选：

- Rust toolchain（如果要用 real runner 跑真实 cargo test）
- C2Rust 可执行文件（如果要做真实 C 项目→Rust baseline 的转译链路）

# 6. 快速开始

以下命令以 Windows PowerShell 为例。默认项目路径为 `F:\program_uni\RAGtest\C2Rust`。

## Step 1：启动 PostgreSQL（pgvector）

使用 Docker 启动数据库容器（容器名固定为 proj_postgres）：

```powershell
docker inspect proj_postgres *> $null
if ($LASTEXITCODE -ne 0) {
  docker run -d --name proj_postgres -e POSTGRES_USER=root -e POSTGRES_PASSWORD=root -e POSTGRES_DB=postgres -p 5432:5432 pgvector/pgvector:pg15
} else {
  docker start proj_postgres
}
```

## Step 2：初始化数据库（schema + lexical_search）

如果你的系统允许执行 ps1（推荐）：

```powershell
cd F:\program_uni\RAGtest\C2Rust
.\scripts\init_db.ps1
```

如果 ps1 被禁用（可选替代）：

```powershell
cd F:\program_uni\RAGtest\C2Rust
Get-Content .\db\schema.sql -Raw | docker exec -i -e PGPASSWORD=root proj_postgres psql -U root -d postgres
Get-Content .\retrieval\sql\lexical_search.sql -Raw | docker exec -i -e PGPASSWORD=root proj_postgres psql -U root -d postgres
```

## Step 3：启动 API

Docker 在本项目里主要用于数据库。API 推荐本机启动，原因是：

- demo/pilot 会传入 Windows 的 workspace 路径；如果 API 跑在容器里，需要额外做路径映射，否则会看不到本地文件。

启动命令：

```powershell
cd F:\program_uni\RAGtest\C2Rust\apps\api
$env:PYTHONPATH="F:\program_uni\RAGtest\C2Rust"
$env:DATABASE_URL="postgresql://root:root@localhost:5432/postgres"
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

## Step 4：检查 /health

另开一个 PowerShell 窗口：

```powershell
curl.exe -s http://127.0.0.1:8000/health
```

期望输出：

```json
{"ok":true,"db":"ok"}
```

## Step 5：运行 demo

```powershell
cd F:\program_uni\RAGtest\C2Rust
$env:DATABASE_URL="postgresql://root:root@localhost:5432/postgres"
python .\scripts\run_demo.py --api http://127.0.0.1:8000
```

## Step 6：运行 pilots

```powershell
cd F:\program_uni\RAGtest\C2Rust
$env:DATABASE_URL="postgresql://root:root@localhost:5432/postgres"
python .\scripts\run_pilots.py --api http://127.0.0.1:8000 --out .\experiments.csv
```

脚本会输出 4 个 run_id（2 个 pilot × baseline/enhanced）。

## Step 7：查看 experiments.csv

`experiments.csv` 会出现在你指定的路径（上面的命令里是仓库根目录）。

也可以单独导出（从数据库汇总）：

```powershell
cd F:\program_uni\RAGtest\C2Rust
$env:DATABASE_URL="postgresql://root:root@localhost:5432/postgres"
python .\scripts\export_experiments_csv.py --out experiments.csv
```

# 7. Demo 说明

demo 的作用是：用一个极小 workspace 稳定走通“检索→补丁→验证→诊断→回滚/停止→记录指标”的主链路，让你能在答辩时展示系统每一步都在工作。

它不是正式大规模实验，也不追求每次都修复成功。相反，demo 失败也有价值：它能证明检索、补丁生成、执行验证、诊断、回滚与停止条件都能产出可追踪记录。

demo 输出/运行记录里常用的关键字段：

- run_id：一次运行的唯一标识，用于打开 `/runs/{id}` 查看完整记录
- target_file：本次补丁目标文件（从证据与边界中选出）
- evidence_top：检索命中的证据条目（用于解释“为什么这么改”）
- strategy_evidence_top：更偏策略/约束类的证据（用于解释“怎么改才安全”）
- patch_preview：补丁预览（unified diff 的截断片段）
- final_status：最终状态（OK/FAILED）
- final_stop_reason：停止原因（success/no_progress/apply_fail/compile_fail 等）
- iteration_count：迭代轮次（enhanced 才会多轮）
- rollback_count：回滚次数（失败或无进展时回滚）

# 8. Pilot 实验说明

## baseline 与 enhanced 的区别

- baseline：只做编译/测试验证与诊断记录；不做检索增强、不生成补丁、不应用补丁。
- enhanced：在 baseline 之上跑完整闭环：检索 → 生成补丁 → 应用 → build/test → 诊断 →（回滚或停止），并限制最大轮次。

## 为什么是两个 pilot

pilot 的目标是“用很小的代价把实验链路跑通，并得到能写论文的对照结果”，所以选择两个规模很小、依赖很少的 workspace：

- pilot-1（流程验证型）：强调“跑得稳、能导出表”，即使失败也要可解释。
- pilot-2（对照展示型）：强调“baseline vs enhanced 能出现差异”，用于论文第四章对比表格。

## experiments.csv 里有什么字段

典型字段包括：

- 结果：final_status、compile_ok、test_ok、diagnose_issue_count
- 代价：iteration_count、patch_rounds、rollback_count、total_ms（以及 retrieve/generate/execute 分项耗时）
- 失败解释：primary_error_kind、final_stop_reason
- 安全性（轻量近似统计）：unsafe_blocks、raw_ptr_count、unsafe_api_count

# 9. 结果文件说明

- `/runs/{id}`：查看一次 run 的完整记录（steps/patches/metrics/summary），用于调试与答辩截图。
- `experiments.csv`：从数据库汇总得到的实验结果表，用于论文第四章表格。
- `docs/EXPERIMENTS.md`：对 baseline/enhanced 的实验口径、导出命令与字段解释的补充说明。

# 10. 项目边界与当前局限性

这是一套本科毕设原型。

- 本项目没有重写 C2Rust，只是在 C2Rust baseline 输出之上做后处理强化。
- 没有做复杂的图分析（CFG/PDG/CPG 等）或工业级证据图谱；风险定位与切片边界是轻量近似。
- Repair Agent 是最小多轮闭环，目的是可复现与可追踪，不是追求极致修复成功率。
- 安全性指标是轻量字符串统计近似，用于趋势展示与小规模对比，不等价于严格静态分析。
- 当前实验以 demo/pilot 规模为主；不宣称覆盖大规模开源项目 benchmark。

# 11. 项目目录说明

- apps/api：FastAPI 服务、Agent/FSM、Runner、Diagnose、补丁生成与应用等核心逻辑
- retrieval：检索逻辑与 SQL（向量检索/词法检索/融合排序）
- db：数据库 schema 与 migrations
- scripts：demo、pilots、CSV 导出等可复现脚本入口
- docs：实验口径与说明文档（例如 docs/EXPERIMENTS.md）
