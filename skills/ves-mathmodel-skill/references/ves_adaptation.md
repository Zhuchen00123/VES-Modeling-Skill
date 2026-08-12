# VES 多 slice 宿主验证契约 (通用接缝)

> 本文档定义 `scripts/run_ves_problem.py` 的通用契约：如何把任意 VES 垂直切片接入 Stage 2/3/5/8/9。回归/预测专项细节见 `references/ves_regression.md`；本文为所有 slice 的公共规则。

## 1. 覆盖范围（VES-Modeling R7.3/R31）

通用调度器按 `ves_modeling.<slice>` 公开 API 动态路由，当前目录覆盖 25 类 slice：

| 类型 | slices | 宿主目录 |
|---|---|---|
| 有 host 真值（labels/参数/序列） | regression, forecasting, classification, ode, clustering, anomaly, recommendation, probabilistic, association, survival, markov, changepoint, seqpattern | 必须提供 |
| 完整公开实例（无 host 目录） | optimization, graph, montecarlo, multiobjective, queueing, assignment, binpacking, lqr, sir, cellular, networksir, game | 不需要 |

`python <skill>/scripts/run_ves_problem.py --list-slices` 可随时查看目录；`--check-only --slice <name>` 检查该 slice 后端能力与 `capabilities()`。

## 2. 接缝原则

- 只 import 公开符号：`run_<slice>_search`、`apply_<slice>_solution`、`capabilities()`、`API_SCHEMA_VERSION`、公开结果类型（优先 `to_summary()`）。
- 不 import Verifier/Judge/SearchEngine/Runner/generator 等内部实现，不复制 VES 代码。
- 版本漂移通过能力检测（签名 + 字段白名单）收敛：`public_dir/drafts/improves/workspace/generator` 必须存在于 `run_*_search` 签名；`capabilities()` 缺省时 verified metrics 为空并照实记录。
- slice 特有参数（如 classification 的 `classes`、forecasting 的 `frequency/row_order`、optimization 的 `tolerance`）通过 `--set key=value` 传入，取值支持 JSON 或逗号列表。

## 3. 数据与安全前置（fail-closed）

1. `public_dir` 与 `host_dir` 不得相等或嵌套（host leak）。
2. `public_dir` 不得包含任何已知宿主文件（`hidden_test_labels.csv`、`hidden_test_values.csv`、`hidden_test_ratings.csv`、`hidden_parameters.json`、`hidden_test_transactions.csv`、`hidden_test_outcomes.csv`、`hidden_test_changepoints.csv`、`hidden_test_sequences.csv`）。
3. 目录内已知必需的 public 文件（如 `train.csv`+`test_features.csv` 或 `problem.json`）缺失即报错；其余更细的数据契约交给 VES 自身的 `validate_*_data` 严格校验（契约不合 → 后端错误，CLI 退出码 4）。
4. 需要 host 的 slice 必须显式提供 `--host-dir`。
5. 真实 LLM 候选只走 `generator=llm` + Docker；`mock` 仅限可信夹具本地运行。

## 4. normalized Evidence manifest（schema 1.1）

搜索与 apply 都原子写 JSON（临时文件 + `os.replace`），统一结构：

```json
{
  "schema_version": "1.1",
  "operation": "search|apply",
  "slice": "<slice>",
  "backend": {
    "name": "ves_modeling.<slice>",
    "capability": {"available": true, "has_search": true, "has_apply": true, "has_capabilities": true},
    "api_schema_version": "1.0",
    "package_version": "<版本或 null>",
    "verified_metrics": ["accuracy", "macro_f1", "..."]
  },
  "task": {"slice": "<slice>", "dataset_name": "...", "generator": "mock|llm", "drafts": 2, "improves": 3, "public_dir": "<str>", "host_dir": "<str 或 null>"},
  "result": {
    "status": "verified|no_verified|produced_unverified",
    "run_id": "<id>",
    "metrics": {"<verified_metric>": <数值或 null>},
    "rejected": 0,
    "candidate_id": "<id 或 null>"
  },
  "data_contract": {...},
  "artifacts": {"run_dir": "<str>", "summary": "<str>", "best_solution": "<str>", "predictions": "<str 或 null（仅 apply 写入；search 无此键）>"},
  "provenance": {"files_sha256": {...}, "best_code_sha256": "...", "generation_params": {...}, "generated_utc": "..."}
}
```

- metrics 只取 `capabilities()["verified_metrics"]` 对应的宿主字段（`best_<metric>` / `to_summary()`），**candidate 自评一律不读**。
- `best_code`/`records`/Evidence 内容不进 manifest，只留路径与哈希。
- apply 结果没有 metrics：未知真值下状态恒为 `produced_unverified`，只记录预测文件与哈希。

## 5. 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 搜索完成且 `status=verified`（可作证据） |
| 1 | 输入/前置校验错误 |
| 2 | 后端不可用 / 能力签名缺失 / apply 入口缺失 |
| 3 | 搜索完成但 `status != "verified"`（manifest 已写，不可当证据） |
| 4 | 搜索/apply 过程意外异常 |
| 5 | apply 完成且 `status=produced_unverified`（预测已产出，**永远不是证据**） |

## 6. Stage 接入

- Stage 2：每个 Qi 写 `ves_eligibility`、`ves_slice`（regression/forecasting/classification/...）、`ves_reason`、`ves_data_contract`；无法满足契约时 `ves_eligibility=false|unclear`。
- Stage 3：写 `execution_backend=ves|local|both`、`verifier_compatible`、`out_of_ves_scope`。
- Stage 5：`python <skill>/scripts/run_ves_problem.py --slice <name> --public-dir ... [--host-dir ...] --workspace ... --generator mock|llm [--set key=value ...]`，然后把 manifest 写入 `decision_log.stages.5.sub_problems.<Qi>`：`ves_run_id/ves_status/ves_slice/ves_metrics/evidence_ref/manifest_path`。
- Stage 8：论文只引用 `status=verified` 且 `ves_metrics` 与 manifest 一致的指标；`produced_unverified` 只能标注“已生成、未验证”。
- Stage 9：有 `ves_eligibility=true` 的 Qi 必须校验 manifest/artifacts/hash/指标一致，否则编译/提交 fail-closed。
