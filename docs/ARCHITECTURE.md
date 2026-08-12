# 架构与信任边界

## 目标

VES-Modeling-Skill 不是新的通用求解器。它在成熟数学建模竞赛工作流外壳中增加一个可验证计算接缝，让 Agent 负责“解什么、为什么这样解、如何表达”，让 VES-Modeling 负责“哪个可执行方案经独立验证后更好”。

## 分层职责

| 层 | 负责 | 不负责 |
|---|---|---|
| 数学建模 Skill | 读题、拆题、模型候选、假设、鲁棒性、决策状态、论文与合规 | 实现 VES 的 Verifier、Judge、SearchEngine 或候选沙箱 |
| VES 薄适配器 | 输入预检、公开 API 能力检测、调用、Evidence 归一化、fail-closed 门 | 读取 candidate 自报分数、绕过 VES 验证、导入私有模块 |
| VES-Modeling 宿主 | 候选生成、隔离执行、独立验证、比较与最优解选择 | 竞赛题意解释、主观建模决策、论文叙事 |
| LaTeX 论文层 | 只引用已验证 manifest、编译、规则与引用一致性终审 | 把未验证输出包装成确定结论 |

## 回归数据流

```text
Stage 2
  判定 VES eligibility，并声明 target / feature / ID / row-order 契约
       │
       ▼
Stage 3
  选择 execution_backend，检查 verifier_compatible
       │
       ▼
Stage 5
  public/train.csv + public/test_features.csv
  host/hidden_test_labels.csv
       │
       ▼
scripts/run_ves_regression.py
  ├─ 拒绝 public/host 路径嵌套或泄漏
  ├─ 校验列、行数、ID 与显式行序授权（target_column/id_column/row_order）
  ├─ 懒加载 ves_modeling.regression 公共 API + capabilities()
  ├─ search：调用 run_regression_search → RegressionSearchResult
  └─ apply：调用 apply_regression_solution → produced_unverified
       │
       ▼
VES RegressionSearchResult
       │
       ▼
normalized manifest
  ├─ status / run_id
  ├─ verified_rmse / verified_mae
  ├─ data_contract / api_schema_version
  ├─ evidence_ref / artifact paths
  ├─ data/code hashes
  └─ capability + provenance
       │
       ▼
decision_log Stage 5 → Stage 8 引用 → Stage 9 一致性终审
```

## 信任规则

1. 只调用 `ves_modeling.regression` 的公开 API（`run_regression_search`、`apply_regression_solution`、`capabilities`）；VES 内部模块名或对象不是兼容契约。
2. 只接受 `RegressionSearchResult.best_rmse` 与 `best_mae` 等宿主验证字段；candidate 自报指标没有证据资格。
3. `status != verified` 时仍可写诊断 manifest，但命令必须非零退出，且论文引用门保持关闭。
4. apply 结果状态恒为 `produced_unverified`：没有官方标签，不产出任何质量指标，永远不可作为证据引用。
5. manifest 不复制 `best_code`、完整 records 或 Evidence 内容，只保存引用、摘要与哈希。
6. 公开数据目录与宿主隐藏标签目录必须物理分离，且不能互相嵌套。
7. 缺少共享 ID 时，只有显式 `--assume-row-order` 才能采用行序对齐；共享单一 ID 时必须逐行一致。
8. 论文中的 verified 指标必须能够回溯到仍存在的 manifest、artifact 与匹配哈希。

## 兼容策略

VES 正在持续迭代，因此适配器不硬编码 VES 包版本来判断兼容性，而是在运行时检查：

- `run_regression_search` 是否存在；
- 必需参数是否可用；
- `apply_regression_solution` 与 `capabilities()` 是否可用（apply 模式）；
- `RegressionSearchResult` 是否提供规范化所需字段；
- 返回的关键 artifact 是否真实存在并与内容哈希一致。

新增 VES 版本时，优先扩展能力检测和字段白名单，不复制其内部实现，也不为尚未存在的通用任务接口提前建设复杂 registry。

## 退出码

| 退出码 | 含义 |
|---:|---|
| 0 | 搜索完成且结果已验证 |
| 1 | 输入或预检失败 |
| 2 | VES 后端不可用或公共能力不兼容 |
| 3 | 搜索完成但没有 verified 结果 |
| 4 | VES 运行、artifact 或不变量失败 |

机器调用方必须同时检查退出码和 manifest 的 `status`，不能只检查文件是否生成。
