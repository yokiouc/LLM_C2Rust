# 论文复现实验步骤（Iteration 8）

## 环境准备

- Python 3.10+
- Postgres 15（已初始化 schema）
- 可选：OpenAI Key（若使用真实 LLM 后端）

预期耗时：5–15 min（取决于依赖安装与数据库可用性）

## 配置

- 受控提示词模板： [controlled_prompt.md](file:///f:/program_uni/RAGtest/c2rust/apps/api/patch/controlled_prompt.md)
- 收敛策略 YAML： [convergence.yaml](file:///f:/program_uni/RAGtest/c2rust/apps/api/patch/convergence.yaml)

说明：

- 运行时只做占位符替换：`{evidence}` 与 `{target_function}`，不拼接其他自由文本。
- 可通过命令行覆盖 YAML 中的 `max_iters` 与 `no_progress_limit`。

## 运行命令

在 `apps/api/` 目录下：

1) 准备 Evidence 文件（示例：`evidence.json`）

内容应是单个 JSON 对象，至少包含 `file` 与 `slice` 字段，用于离线规则模板生成最小补丁。

2) 执行收敛循环并导出指标

```bash
python cli.py converge_patch <BASE_DIR> evidence.json <TARGET_FUNCTION> <OUT_DIR> --max-iters 20 --no-progress-limit 5
```

预期输出：

- 第一行 JSON：包含 `best_diff_len/iters/config_hash/ms`
- 随后输出 best diff（可能为空）
- `<OUT_DIR>` 下生成 `{iteration:04d}.csv/.json` 与对应 `.sha256`

预期耗时：单漏洞 1–10 min（含测试的情况下取决于 validate_cmd；若不传 `--validate-cmd`，通常 < 30s）

## 指标文件检查（一键验证）

在 `C2Rust/` 目录下：

```bash
python scripts/verify_reproduce.py --metrics-dir <OUT_DIR>
```

预期输出示例：

```json
{"ok": true, "csv": 20, "json": 20}
```

## 故障排查

- 若使用 OpenAI 后端：设置 `PATCH_BACKEND=openai` 与 `OPENAI_API_KEY`
- 若无网络/无 Key：默认 `PATCH_BACKEND=template`（离线可复现）
- 若出现补丁为空：检查 Evidence 是否包含 `file/slice`，以及提示词模板是否满足 5 条硬约束

