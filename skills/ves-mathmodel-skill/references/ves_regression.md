# VES 回归宿主验证契约 (ves-mathmodel-skill)

> 本文档是回归/预测类子问题接入 VES 宿主验证的唯一契约。Stage 2/3/5/8/9 的相关字段定义以本文档为准；`decision_log.json` v3.2 只保存契约要求的稳定字段。

> 其他 VES slice（分类、时序、优化、ODE 等 25 类）走通用调度器 `scripts/run_ves_problem.py`，契约见 `references/ves_adaptation.md`；本文为回归专项。

## 1. 边界 (谁负责什么)

```
Stage 2 (标记 Qi 的 ves_eligibility + data contract)
  ↓
Stage 3 (execution_backend=ves / verifier_compatible / out_of_ves_scope)
  ↓
Stage 5 (scripts/run_ves_regression.py)
  ├─ search 模式: 调用 ves_modeling.regression.run_regression_search
  │    得到 RegressionSearchResult (宿主 verifier 产出 rmse/mae)
  └─ apply 模式: 调用 ves_modeling.regression.apply_regression_solution
       对未知官方测试特征生成预测, 状态恒为 produced_unverified
  ↓
normalized Evidence manifest (原子写, 仅稳定字段, schema 1.1)
  ↓
decision_log.stages.5.sub_problems.<Qi> (ves_run_id/status/verified_rmse/verified_mae/evidence_ref/manifest_path)
  ↓
Stage 8 (论文只引用 verified 指标) → Stage 9 (manifest/artifacts/hash 一致性门, fail-closed)
```

**接缝原则**: 本 skill 不复制、不 import VES 内部实现（Verifier/Judge/SearchEngine/Runner/generator/runner 均视为私有或内部实现）。只允许 `import ves_modeling.regression` 公开符号 `run_regression_search`、`apply_regression_solution`、`capabilities`、`API_SCHEMA_VERSION` 与公开结果类型。VES 仍在迭代，任何版本漂移通过 `scripts/run_ves_regression.py` 的能力检测与字段白名单收敛，不绑定 demo 或私有接口。

## 2. 数据契约

### 2.1 目录与文件

| 角色 | 路径 | 内容 | 可见性 |
|---|---|---|---|
| public | `<public_dir>/train.csv` | 训练集（含 `target` 列 + 特征列） | 候选可见 |
| public | `<public_dir>/test_features.csv` | 测试特征（**不含** `target`；特征列与 train 一致） | 候选可见 |
| host | `<host_dir>/hidden_test_labels.csv` | 隐藏标签（至少含 `target` 列） | 仅宿主，绝不给候选 |

**前置校验（fail-closed）**：
1. `public_dir` 不得包含 `hidden_test_labels.csv`（泄漏即拒绝执行）。
2. `train.csv` 必须含 `target` 列；`test_features.csv` 不得含 `target`。
3. `test_features.csv` 特征列必须与 `train.csv`（去掉 `target` 后）**按顺序完全一致**（`test_cols == [c for c in train_cols if c != "target"]`）；重排、缺失、多余、重复或含空白/空表头的列名一律报错。
4. `hidden_test_labels.csv` 行数必须等于 `test_features.csv` 行数（宿主按行对应验证预测）。

### 2.2 行序 / ID 契约

- **默认契约（要求共享 ID）**: `test_features.csv` 与 `hidden_test_labels.csv` 必须存在**同一个可对齐的 ID 列**（如 `id`），脚本按该列逐行比对；不一致即报错（fail-closed）。此时 `hidden_test_labels.csv` 的第 i 行必须对应 `test_features.csv` 中同 ID 的行。
- **唯一例外（显式 opt-in）**: 仅当两边缺少可对齐 ID 列（或共享列多于 1 列导致歧义）时，必须显式 `--assume-row-order`（或 `assume_row_order=True`）才允许纯行序对齐；否则清晰报错。**优先 fail-closed**，不得静默假设行序。

### 2.3 结果契约（R7.3 稳定字段）

search 模式只读 `RegressionSearchResult` 字段：`run_id`、`dataset_name`、`generator`、`status`、`drafts`、`improves`、`best_code`、`best_candidate_id`、`best_rmse`、`best_mae`、`rejected`、`run_dir`、`candidates`、`data_contract`，以及 JSON 视图 `to_summary()`（`API_SCHEMA_VERSION=1.0`）。其中 `best_rmse/best_mae` 只来自宿主 verifier 证据（`best_evidence`），**candidate 自评字段一律不读**。

apply 模式只读 `ApplyRegressionResult` 字段：`status`、`run_id`、`run_dir`、`predictions_path`、`code_sha256`、`data_sha256`、`predictions_sha256`、`runner`、`docker_image`、`docker_digest`、`data_contract`。**apply 永远没有质量指标**：没有官方测试标签，任何 RMSE/MAE 都不存在。

## 3. 运行边界 (mock / llm)

| generator | 用途 | 运行边界 |
|---|---|---|
| `mock` | 可信夹具 / 本地自检（tests/fixtures、fixture_dir） | **仅限本地**，禁止用于真实候选结果 |
| `llm` | 真实候选生成 | **必须 Docker runner**（`--image`），本地容器外执行一律拒绝 |

两种模式下，只有 `status=verified` 的结果可写入决策日志并最终被论文引用；`no_verified` 不是成功证据。

## 4. 能力检测与签名（不硬编码包版本）

`scripts/run_ves_regression.py` 在调用前做稳定符号检测：
- 模块 `ves_modeling.regression` 可导入；
- search 模式：`run_regression_search` 存在且签名接受本脚本传入的参数（`public_dir, host_dir, drafts, improves, workspace, generator, dataset_name, fixture_dir, fallback_code, image, image_digest, timeout_seconds, target_column, id_column, row_order, split_metadata`）；
- apply 模式：`apply_regression_solution` 存在且签名接受 `solution, public_dir`（含 `workspace/trusted_code/image/image_digest/timeout_seconds/target_column/id_column/row_order`）；
- 可选增强：`capabilities()` 返回 JSON 能力声明、`API_SCHEMA_VERSION` 存在；
- `RegressionSearchResult` 存在且含 §2.3 的必要字段。

检测失败 → 明确报错并退出（CLI 退出码 2），不猜测、不降级、不伪装。

## 5. normalized Evidence manifest（`scripts/run_ves_regression.py` 输出）

原子写入（临时文件 + `os.replace`），JSON 仅含稳定字段：

```json
{
  "schema_version": "1.1",
  "operation": "search|apply",
  "backend": {
    "name": "ves_modeling.regression",
    "capability": {"available": true, "has_run_regression_search": true, "has_apply_regression_solution": true, "has_capabilities": true, "result_fields_ok": true},
    "api_schema_version": "1.0",
    "package_version": "<importlib.metadata 探测值或 null>"
  },
  "task": {
    "dataset_name": "regression",
    "generator": "mock|llm（search）",
    "trusted_code": false（apply）,
    "drafts": 2,
    "improves": 3,
    "public_dir": "<str>",
    "host_dir": "<str>"
  },
  "result": {
    "status": "verified|no_verified|produced_unverified",
    "run_id": "<12 hex>",
    "rmse": null（apply 无此字段）,
    "mae": null（apply 无此字段）,
    "rejected": 0,
    "candidate_id": null,
    "predictions_sha256": null（search 无此字段）
  },
  "data_contract": {"target_column": "target", "id_column": null, "row_order": "input", ...},
  "artifacts": {
    "run_dir": "<str>",
    "summary": "<run_dir>/summary.json",
    "config": "<run_dir>/config.json（search）",
    "best_solution": "<run_dir>/best_solution.py（search）",
    "predictions": "<run_dir>/candidate/predictions.json（apply）"
  },
  "provenance": {
    "files_sha256": {"public/train.csv": "<sha256>", "public/test_features.csv": "<sha256>", "host/hidden_test_labels.csv": "<sha256>"},
    "best_code_sha256": "<sha256 或 null>",
    "generation_params": {"image": "...", "image_digest": "...", "timeout_seconds": 900.0, "fixture_dir": "...", "target_column": "target", "id_column": null, "row_order": "input", "split_metadata": null},
    "generated_utc": "2026-08-11T08:00:00Z"
  }
}
```

**禁止序列化**：`best_evidence`、`records`、`best_code` 内容不进 manifest（只留路径与 hash）；apply 不写任何质量指标。

**退出码**：

| 退出码 | 含义 |
|---|---|
| 0 | 搜索完成且 `status=verified`（可作证据） |
| 1 | 输入/前置校验错误（缺文件、泄漏、特征/行序不一致等） |
| 2 | 后端不可用 / 能力签名缺失（search 或 apply） |
| 3 | 搜索完成但 `status != "verified"`（manifest 已写，但**不可当成功证据**） |
| 4 | 搜索过程意外异常（后端错误） |
| 5 | apply 完成且 `status=produced_unverified`（预测文件已产出；**永远不是证据**） |

## 6. 决策日志与论文引用

- Stage 2：每个 Qi 写 `ves_eligibility`（true/false/unclear）、`ves_reason`、`ves_data_contract`（public/host 文件、行序/ID 契约）。
- Stage 3：写 `execution_backend`、`verifier_compatible`、`out_of_ves_scope`。
- Stage 5：运行脚本后写 `ves_run_id`、`ves_status`、`verified_rmse`、`verified_mae`、`evidence_ref`（`ves_run_id` + provenance hash 引用）、`manifest_path`。
- Stage 5 apply：未知官方测试特征产出 `ves_apply_run_id`、`ves_apply_status=produced_unverified`、`predictions_path`、`predictions_sha256`、`code_sha256`、`apply_manifest_path`；不得写入 `verified_rmse/verified_mae`。
- Stage 8：论文只引用 normalized verified 指标（LaTeX-first）；未 verified 的数值不得入文；`produced_unverified` 预测如需入图/入附录必须强制标注“已生成、未验证”，且不得出现在摘要或结论中作为效果证据。
- Stage 9：有回归子问题时必须 `status=verified`、`manifest_path` 与 artifacts/hash 存在、论文引用与 manifest 一致；不满足即编译/提交 fail-closed。

## 7. 范围外与非回归子问题

- 非回归/预测子问题（当前 Skill 只接回归切片）标记 `out_of_ves_scope=true`，走常规本地建模 + 本地验证；**不得**写成 VES 已验证。
- 未知官方测试集上的"预测"通过 `apply_regression_solution` 产出，状态恒为 `produced_unverified`；必须标注“已生成、未验证”，**不可引用为宿主证据**，也不得生成/引用任何 RMSE/MAE。
- VES-Modeling 上游已扩展到 25 类稳定 slice（含分类、时序、优化、ODE 等），每个 slice 都有 `run_*_search` 与 `apply_*_solution`；本 Skill 当前只实现回归切片的薄适配器，其余 slice 的适配按 `docs/VES_ADAPTATION_ROADMAP.md` 逐步接入。
