# C2Rust Unsafe Rust Repair System

本科毕设工程原型：基于 C2Rust 转译产物的 unsafe Rust 自动修复系统。

## 项目定位

- **C2Rust** 是基线迁移工具：将 C 代码转译为可编译的 unsafe Rust
- **本项目** 不重写 C2Rust，而是围绕其转译产物做自动化安全修复与验证
- 研究范围：C99 → C2Rust baseline → safer Rust repair

## 系统架构

```mermaid
graph TD
    C[C Source Code] -->|c2rust| B[Baseline Rust]
    B --> HD[Hotspot Discovery]
    HD --> SB[Slice Builder]
    SB --> RAG[Evidence Retrieval<br/>lexical + vector + RRF]
    RAG --> PB[Prompt Builder]
    PB --> PG[Patch Generator<br/>LLM / Template]
    PG --> PV[Patch Validator]
    PV --> AP[Apply Patch]
    AP --> VR[Validation Runner<br/>build / test / clippy / fmt]
    VR -->|pass| SC[Score Progress]
    VR -->|fail| DG[Diagnose]
    DG --> RB[Rollback]
    RB --> SC
    SC -->|improved| RAG
    SC -->|converged| OK[SUCCESS]
    SC -->|no progress| NP[STOP_NO_PROGRESS]
    SC -->|max iters| MI[STOP_MAX_ITERS]

    DB[(PostgreSQL + pgvector)]
    HD -.-> DB
    SB -.-> DB
    RAG -.-> DB
    VR -.-> DB
    SC -.-> DB
```

## 目录结构

```
C2Rust/
├── apps/
│   ├── api/                    # FastAPI 后端 API
│   │   ├── main.py             # API 入口 + 路由
│   │   ├── agent/fsm.py        # Legacy FSM + run_fsm_v2() 入口
│   │   └── tests/              # 131+ 测试
│   └── web/                    # Next.js 前端
│       └── src/app/            # Dashboard / Run Detail / Compare
├── packages/
│   ├── core/                   # 配置、常量、类型、DB 连接
│   ├── evidence/               # 证据库、检索、RRF、chunker
│   ├── repair/                 # hotspot、slice、patch、FSM agent
│   ├── runner/                 # cargo 执行、分步验证
│   └── metrics/                # 安全性指标、收集、导出、对比
├── db/
│   ├── schema.sql              # 完整 schema (16 张表)
│   └── migrations/             # 增量 migration (002-006)
├── scripts/                    # demo、pilot、导出脚本
├── demo_workspace/             # Demo Rust 工作空间
├── pilot0_workspace/           # Pilot 0 工作空间
├── pilot1_workspace/           # Pilot 1 工作空间
└── experiments.csv             # 实验数据导出
```

## 快速开始

### 1. 数据库初始化

```bash
# 启动 PostgreSQL (需要 pgvector 扩展)
docker run -d --name c2rust-pg -e POSTGRES_USER=root -e POSTGRES_PASSWORD=root \
  -p 5432:5432 pgvector/pgvector:pg16

# 初始化 schema
export DATABASE_URL=postgresql://root:root@localhost:5432/postgres
psql $DATABASE_URL -f db/schema.sql
```

### 2. 启动后端

```bash
cd apps/api
pip install -r requirements.txt
DATABASE_URL=postgresql://root:root@localhost:5432/postgres uvicorn main:app --port 8000
```

### 3. 启动前端

```bash
cd apps/web
npm install
npm run dev
# 访问 http://localhost:3000
```

### 4. 运行 Demo

```bash
# 使用 legacy FSM
python scripts/run_demo.py --api http://localhost:8000

# 使用新 FSM (v2)
python scripts/run_demo.py --api http://localhost:8000 --use-v2

# 指定模式
python scripts/run_demo.py --mode baseline
python scripts/run_demo.py --mode enhanced
```

### 5. 运行 Pilot 实验

```bash
python scripts/run_pilots.py --api http://localhost:8000 --out experiments.csv
```

### 6. 导出论文表格

```bash
python scripts/export_paper_tables.py --out results/
```

## 前端页面

| 页面 | 路由 | 功能 |
|------|------|------|
| Dashboard | `/` | Runs 列表 + 摘要卡片 |
| Run Detail | `/runs/[id]` | FSM 时间线 + Hotspots/Slices + Patches Diff + Validation + Metrics |
| Compare | `/compare` | Baseline vs Enhanced 对比（正确性/安全性/代价） |

## API 端点

| Method | Path | 说明 |
|--------|------|------|
| `POST` | `/agent/run` | Legacy FSM 运行 |
| `POST` | `/agent/run_v2` | 新 FSM 引擎运行 |
| `GET` | `/runs` | 运行列表 |
| `GET` | `/runs/{id}` | 运行详情 |
| `GET` | `/runs/{id}/status` | 运行状态 + progress |
| `GET` | `/runs/{id}/steps` | FSM 步骤时间线 |
| `GET` | `/runs/{id}/hotspots` | 热点列表 |
| `GET` | `/runs/{id}/slices` | 切片列表 |
| `GET` | `/runs/{id}/validation` | 验证结果 |
| `GET` | `/runs/{id}/patches` | 补丁 + 回滚 |
| `GET` | `/runs/{id}/metrics` | 工程/论文指标 |
| `GET` | `/compare` | Baseline vs Enhanced |
| `POST` | `/retrieve` | 混合检索 |

## Repair Agent FSM 状态

```
INIT → PRECHECK → HOTSPOT_DISCOVERY → SLICE_SELECT
→ RETRIEVE_EVIDENCE → BUILD_PROMPT → GENERATE_PATCH
→ VALIDATE_PATCH → APPLY_PATCH → RUN_BUILD → RUN_TEST → RUN_LINT
→ SCORE_PROGRESS → {SUCCESS | STOP_NO_PROGRESS | STOP_MAX_ITERS}
```

失败路径: `→ DIAGNOSE → ROLLBACK → SCORE_PROGRESS → ...`

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+ / FastAPI / psycopg |
| 数据库 | PostgreSQL 15 + pgvector |
| 前端 | Next.js / TypeScript / Tailwind / shadcn/ui |
| 代码分析 | tree-sitter (Rust parser) |
| 检索 | tsvector (lexical) + pgvector (semantic) + RRF |
| 补丁生成 | Template / OpenAI GPT-4o-mini |

## 配置项

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接串 | (必须设置) |
| `USE_FSM_V2` | 启用新 FSM 引擎 | `false` |
| `RUNNER_MODE` | mock / real | `mock` |
| `RETRIEVAL_MODEL_ID` | 嵌入模型 | `stub-1536` |
| `PATCH_BACKEND` | template / template_edit / openai | `template` |
| `NEXT_PUBLIC_API_URL` | 前端 API 地址 | `http://127.0.0.1:8000` |
