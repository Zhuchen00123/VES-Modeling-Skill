# VES-Modeling-Skill

面向 CUMCM、MCM/ICM 与电工杯的端到端数学建模 Skill：复用成熟竞赛工作流，以 VES-Modeling 作为可执行候选搜索与独立验证后端，并坚持 LaTeX-first 论文交付。

> [!IMPORTANT]
> 本仓库是 [`handsomeZR-netizen/mathmodel-skill`](https://github.com/handsomeZR-netizen/mathmodel-skill) 的 GitHub fork。当前实现以其 MIT 许可版本的 commit [`d3941e14`](https://github.com/handsomeZR-netizen/mathmodel-skill/commit/d3941e14d8693fb4a79948e59afff3098734127e) 为基座进行改造；复用范围、删改内容与第三方声明见 [`THIRD_PARTY_NOTICES.md`](skills/ves-mathmodel-skill/THIRD_PARTY_NOTICES.md)。

## 它解决什么问题

数学建模 Agent 擅长理解题目、拆分子问题、选择方法和组织论文，但生成代码后的“自报指标”并不等于可信结果。本项目把职责拆开：

- `ves-mathmodel-skill` 负责题目理解、建模工作流、决策记录、鲁棒性分析、论文组织与合规检查；
- VES-Modeling 负责候选生成、隔离执行、独立验证、Evidence 生成与最优解选择；
- 论文只允许引用由 VES 宿主验证并写入 normalized manifest 的指标；
- 非 VES 能力范围的问题继续走常规建模与验证，不伪装为“已被 VES 验证”。

当前版本通过通用调度器覆盖 VES-Modeling 全部 25 类 slice（回归、时序预测、分类、优化、ODE、聚类、异常检测、图论、蒙特卡洛、多目标、推荐、概率推断、排队、关联规则、生存分析、指派/TSP、马尔可夫、装箱、变点、LQR、序列模式、SIR、元胞自动机、网络传播、微分博弈）；回归/预测为专项最成熟接缝，其余 slice 的深度数据契约与真实案例验证按路线图持续推进。

## 核心能力

- CUMCM、MCM/ICM、电工杯三类竞赛的 10 阶段工作流；
- 可恢复的 `decision_log.json`，支持阶段跳转、回检和多 harness 交接；
- 25 类 VES slice 通用调度器（`run_ves_problem.py --slice <name>`），回归/预测为专项最成熟接缝；
- 出版级图表工具（vendored）：期刊预设样式、矢量导出、DPI/字体审计、源码预检与视觉 QA；
- fail-closed Evidence 契约：未验证结果、缺失产物或哈希不一致均不能进入论文；
- 三套 LaTeX 模板与渲染/合规检查脚本；
- 评分、差异提取、AI 使用披露和环境诊断工具；
- Codex Skills 为一等入口，同时保持 Claude Code 可用的通用 Markdown 工作流。

## 工作流

```text
题目理解与子问题拆分
        ↓
判断是否适合 VES
        ↓
Stage 5 回归/预测子问题
        ↓
ves_modeling.regression.run_regression_search
        ↓
独立验证 + normalized Evidence manifest
        ↓
decision_log
        ↓
Stage 8/9 LaTeX 写作、引用核验与终审
```

其他可验证 slice（分类、时序、优化、ODE、图论等）经 `run_ves_problem.py --slice <name>` 走同一套 Evidence 契约。

完整边界与数据流见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

## 安装

克隆本 fork：

```bash
git clone https://github.com/Zhuchen00123/VES-Modeling-Skill.git
cd VES-Modeling-Skill
```

安装到 Codex 用户级 Skills 目录：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/ves-mathmodel-skill "${CODEX_HOME:-$HOME/.codex}/skills/"
```

也可以把 `skills/ves-mathmodel-skill/` 放到项目级 `.agents/skills/`。更新 Skill 时，替换整个同名目录，避免旧文件残留。

VES 回归适配器依赖宿主环境可导入公开模块 `ves_modeling.regression`。真实 LLM 候选必须由 VES 配置的 Docker runner 执行；本 Skill 不复制 VES 内部实现。

## 快速使用

安装后可直接说：

```text
使用 $ves-mathmodel-skill 开始建模。
竞赛是 CUMCM，题目 PDF 在 ./problem.pdf，距离截止还有 70 小时。
```

Skill 会收集竞赛、题号、队员、截止时间和题面路径，初始化状态，然后从 Stage 0 开始。Stage 2 会为每个子问题判定 `ves_eligibility` 与 `ves_slice`；可映射到 VES slice 且满足数据契约的 Qi 在 Stage 5 进入宿主验证，未覆盖或契约不满足的 Qi 标记 `out_of_ves_scope=true` 走常规建模。

## VES 宿主验证（25 类 slice）

查看当前支持的 slice 目录与后端能力：

```bash
python3 skills/ves-mathmodel-skill/scripts/run_ves_problem.py --list-slices
python3 skills/ves-mathmodel-skill/scripts/run_ves_problem.py --slice regression --check-only
python3 skills/ves-mathmodel-skill/scripts/run_ves_regression.py --check-only
```

回归/预测子问题使用专项适配器：

```bash
python3 skills/ves-mathmodel-skill/scripts/run_ves_regression.py \
  --public-dir <public> --host-dir <host> --workspace runs \
  --generator mock --output state/ves_regression_manifest.json
```

其他 slice 使用通用调度器（有宿主真值的 slice 必须给 `--host-dir`；完整公开实例类如 optimization/graph 不需要；slice 特有参数用 `--set key=value`）：

```bash
python3 skills/ves-mathmodel-skill/scripts/run_ves_problem.py \
  --slice classification --public-dir <public> --host-dir <host> \
  --workspace runs --generator mock --output state/ves_problem_manifest.json
python3 skills/ves-mathmodel-skill/scripts/run_ves_problem.py \
  --slice optimization --public-dir <public> \
  --workspace runs --generator mock --output state/ves_problem_manifest.json
```

输入必须满足物理隔离：

```text
public/                  # 候选可见
├── train.csv
└── test_features.csv

host/                    # 仅宿主可见
└── hidden_test_labels.csv
```

未知真值输入使用 `--apply`（`apply_<slice>_solution`）：状态恒为 `produced_unverified`，只产出预测文件与哈希，绝不产生质量指标。退出码约定：0=verified（可作证据）、1=输入错误、2=后端不可用、3=完成但未 verified、4=运行异常、5=apply 已产出未验证预测。

通用多 slice 契约见 [`references/ves_adaptation.md`](skills/ves-mathmodel-skill/references/ves_adaptation.md)；回归专项的列契约、ID/行序规则与论文引用门见 [`references/ves_regression.md`](skills/ves-mathmodel-skill/references/ves_regression.md)。

## 出版级图表工具（vendored）

绘图能力直接复用 `skills/ves-mathmodel-skill/tools/figure/`（自包含子 skill，不改写），包含：

- `setup_style.py`：nature/science/ieee/general 期刊预设、中文字体自动检测；
- `export_figure.py` / `layout_tools.py`：SVG/PDF/PNG 导出与子图布局；
- `check_figure.py`：格式/DPI/字体嵌入审计；
- `validate_figure.py`：绘图源码静态预检；
- `visual_qa.py` / `profile_data.py`：程序化视觉 QA 与数据剖析；
- `references/`：图表选型、设计理论、期刊规范与投稿检查清单。

使用前先读 `tools/figure/SKILL.md`。VES 绘图 vertical slice 成熟后将整体替换（见路线图与 VES-Modeling Issue #1）。

## LaTeX-first

论文默认从仓库内 LaTeX 模板生成，不把 Markdown 或 Word 当作最终权威源：

- CUMCM：`templates/latex/cumcm/main.tex`，建议 XeLaTeX；
- MCM/ICM：`templates/latex/mcm/main.tex`，建议 pdfLaTeX；
- 电工杯：`templates/latex/diangong/main.tex`，建议 XeLaTeX。

渲染前后均需执行合规检查；当届官方规则优先于仓库中的历史规则基线。

## 验证

从仓库根运行：

```bash
python3 -m unittest discover -s skills/ves-mathmodel-skill/tests -v
python3 skills/ves-mathmodel-skill/scripts/doctor.py --competition cumcm --skip-tools
python3 skills/ves-mathmodel-skill/scripts/doctor.py --competition mcm --skip-tools
python3 skills/ves-mathmodel-skill/scripts/doctor.py --competition diangong --skip-tools
```

当前验证基线：115 项单测通过（3 项因本机无 XeLaTeX 跳过）、三类竞赛 doctor 各 9/9、Skill Creator 校验通过；回归/分类/优化 slice 均以真实 VES mock 闭环验证（`verified`），apply 路径返回 `produced_unverified`。如需验证本地 LaTeX/Pandoc 工具链，移除 `--skip-tools`，并按需要添加 `--require-renderer`。

## 当前边界

- VES 已提供 `apply_regression_solution`：未知官方测试集上的预测状态恒为 `produced_unverified`，必须标注“已生成、未验证”，不能声称有 verified 指标；
- mock generator 只用于可信本地夹具，真实候选必须使用 `generator=llm` 与 Docker runner；
- 纯理论证明、创新机理假设和政策价值判断不应强行交给 VES；
- 通用调度器已覆盖 VES-Modeling 25 类稳定 slice（分类、时序、优化、ODE 等）；回归为专项最成熟，其余 slice 的深度数据契约与真实案例验证按 [docs/VES_ADAPTATION_ROADMAP.md](docs/VES_ADAPTATION_ROADMAP.md) 继续。
- 绘图工具已直接复用成熟实现（`tools/figure/`）；VES 绘图 vertical slice 与 figure manifest/VES 数据入图门禁仍为后续计划（见 [docs/VES_ADAPTATION_ROADMAP.md](docs/VES_ADAPTATION_ROADMAP.md) 与 VES-Modeling Issue #1）。

VES 需要的关键适配和后续建模类别见 [`docs/VES_ADAPTATION_ROADMAP.md`](docs/VES_ADAPTATION_ROADMAP.md)。

## 仓库结构

```text
VES-Modeling-Skill/
├── README.md
├── LICENSE
├── Spec.md
├── idea.md
├── docs/
│   ├── ARCHITECTURE.md
│   └── VES_ADAPTATION_ROADMAP.md
└── skills/
    └── ves-mathmodel-skill/
        ├── SKILL.md
        ├── agents/openai.yaml
        ├── competitions/
        ├── references/
        ├── scripts/
        ├── templates/
        ├── tools/figure/   （vendored 绘图子 skill）
        └── tests/
```

## 许可与来源

本仓库沿用 MIT License。上游 fork 来源、固定 commit、改造点和外部材料边界均在 [`THIRD_PARTY_NOTICES.md`](skills/ves-mathmodel-skill/THIRD_PARTY_NOTICES.md) 中列明。竞赛名称、官方规则、论文、数据集和外部链接仍受各自权利与条款约束。
