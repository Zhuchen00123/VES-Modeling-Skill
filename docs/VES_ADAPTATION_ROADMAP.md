# VES 适配与建模能力路线图

本文区分两类工作：一类是让现有回归接缝可用于真实竞赛交付的关键适配；另一类是逐个增加新的、可独立验证的建模垂直切片。

## P0：回归能力适配现状（2026-08-12，VES R7.3 已交付）

以下此前标注的关键缺口已由 VES-Modeling R7.3 交付，Skill 侧适配器 `scripts/run_ves_regression.py` 已同步支持：

- [x] 公开 `apply_regression_solution`：未知官方测试特征产出预测，状态恒为 `produced_unverified`，绝不伪造 RMSE/MAE；
- [x] 稳定 capability 与结果 schema：`capabilities()` JSON 能力声明 + `API_SCHEMA_VERSION=1.0`；
- [x] 完整 provenance：`provenance.json`（输入哈希、代码哈希、包版本/commit、Docker 镜像身份、脱敏 provider、UTC 时间）；
- [x] 结构化候选与失败日志：统一 `runs/<run-id>/candidates/<attempt>/`，含 `run.json` 分类（生成/沙箱/输出契约/验证失败）；
- [x] 明确数据契约：`target_column`、`id_column`、`row_order`（input/id）、`split_metadata`。

剩余 Skill 侧工作：

- [ ] 宿主运行环境打包（可复现的宿主依赖/镜像，供 LLM client + 公共 API + runner 控制使用）；
- [ ] 其余 24 类 slice 的薄适配器与 Evidence 门禁（见下节）；
- [ ] 可视化 vertical slice（见 Issue #1 与“图形与可视化”节）。

## Skill 侧切片接入顺序（VES 上游已交付 25 类稳定 API）

VES-Modeling 上游已提供 25 类 `run_*_search` / `apply_*_solution` 稳定 API。本 Skill 当前只接入回归；其余切片按真实竞赛案例驱动逐个接入，每个切片都要完成：薄适配器、数据契约与能力检测、normalized Evidence 门禁、Stage 8/9 引用规则、测试夹具与失败语义。不要先做只有抽象类、没有真实 verifier 的通用注册系统。

| 优先级 | 类别 | 最小可验证结果 |
|---:|---|---|
| 1 | 时间序列预测 | 时间感知切分、滚动回测、泄漏检查、预测区间与多步指标 |
| 2 | 分类 | 分层/分组切分、概率校准、阈值策略、类别不平衡指标 |
| 3 | 约束优化 | 可行性检查、约束违反量、目标值复算、确定性基准 |
| 4 | 参数估计与校准 | 参数界、残差诊断、可辨识性与不确定性 |
| 5 | ODE/动力系统 | 数值稳定性、守恒/边界条件、轨迹误差与参数恢复 |
| 6 | 随机模拟 | 随机种子、置信区间、方差与收敛诊断 |
| 7 | 图与网络 | 图数据契约、结构约束、基准图指标与可复现实验 |
| 8 | 空间/时空建模 | 空间切分、邻接与坐标契约、空间泄漏诊断 |
| 9 | 生存与可靠性 | 删失契约、校准、时间依赖指标与可靠性曲线 |
| 10 | 多目标优化 | Pareto 可行性、支配关系复算、权衡与敏感性记录 |

（VES 上游对应 `run_forecasting_search`、`run_classification_search`、`run_optimization_search`、`run_ode_search`、`run_clustering_search`、`run_anomaly_search`、`run_graph_search`、`run_montecarlo_search`、`run_multiobjective_search`、`run_recommendation_search`、`run_probabilistic_search`、`run_queueing_search`、`run_association_search`、`run_survival_search`、`run_assignment_search`、`run_markov_search`、`run_binpacking_search`、`run_changepoint_search`、`run_lqr_search`、`run_seqpattern_search`、`run_sir_search`、`run_cellular_search`、`run_networksir_search`、`run_game_search`。）

## 图形与可视化（待办，不阻塞当前发布）

当前 Skill 提供基础 Matplotlib 图表模板与 300 DPI 导出，但缺少确定性的图表规划、VES Evidence 入图门禁与 LaTeX 图路径契约。可视化增强按“可验证绘图方案”思路逐步建设，已登记到 VES-Modeling 仓库 [Issue #1](https://github.com/Zhuchen00123/VES-Modeling/issues/1)，后续随 VES 公共契约演进：

1. `figure_manifest` + `figure_check`：每张正式图必须绑定 claim、数据源、reader task、发布标记与校验和；
2. VES 数据入图 provenance：`verified` 才可进正文，`no_verified`/`produced_unverified` 仅诊断并强制标注；
3. LaTeX 图路径契约：md 图片路径与输出目录结构校验，防止编译断裂或漏图；
4. 统一视觉规范：固定 palette、字体、矢量导出与色觉友好编码；
5. 复杂图（多面板、Pareto、敏感性、不确定性）再逐步交给 VES 宿主验证并确定性渲染。

图表数量不是质量目标；优先可读、可复现、与结论一致的基础图。

## 可以部分验证、但不能替代人的类别

- 聚类：可验证计算、稳定性和内部指标，不能自动证明簇的现实语义；
- AHP/TOPSIS：可验证矩阵计算、一致性与敏感性，不能替代主观权重的责任主体；
- 因果推断：可验证代码、诊断与敏感性分析，不能仅凭运行结果证明识别假设；
- 政策评价与机理创新：VES 可辅助数值实验，最终假设与价值判断必须由建模者承担。

## 暂不纳入 VES 强制验证

- 纯数学证明；
- 依赖原创洞察的机理构造；
- 无可执行判据的定性论证；
- 不能合法或安全进入候选执行环境的数据与任务。

## 演进原则

1. 先完成第二个真实垂直切片，再评估公共 `Task`/registry 抽象。
2. 保持任务专用 API，例如 `run_forecast_search`，直到共同字段被真实案例验证。
3. 新能力必须先定义 verifier 和失败语义，再接入论文层。
4. 任何未知标签输出都不得冒充 verified 指标。
5. Skill 仅跟随 VES 公共契约演进，不绑定私有实现。
