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

当前 MVP 对回归/预测子问题提供完整 VES 接缝，其他问题类型仍按普通竞赛工作流处理。

## 核心能力

- CUMCM、MCM/ICM、电工杯三类竞赛的 10 阶段工作流；
- 可恢复的 `decision_log.json`，支持阶段跳转、回检和多 harness 交接；
- 回归/预测子问题的 VES 公共 API 薄适配器；
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

Skill 会收集竞赛、题号、队员、截止时间和题面路径，初始化状态，然后从 Stage 0 开始。回归/预测类子问题在 Stage 5 进入 VES；其他问题会明确标记为 `out_of_ves_scope=true`。

## VES 回归适配器

先检查宿主 API 能力：

```bash
python3 skills/ves-mathmodel-skill/scripts/run_ves_regression.py --check-only
```

输入必须分为两个物理隔离目录：

```text
public/                  # 候选可见
├── train.csv
└── test_features.csv

host/                    # 仅宿主可见
└── hidden_test_labels.csv
```

完整列契约、ID/行序规则、退出码、manifest 字段和论文引用门见 [`references/ves_regression.md`](skills/ves-mathmodel-skill/references/ves_regression.md)。

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

如需验证本地 LaTeX/Pandoc 工具链，移除 `--skip-tools`，并按需要添加 `--require-renderer`。

## 当前边界

- VES 已提供 `apply_regression_solution`：未知官方测试集上的预测状态恒为 `produced_unverified`，必须标注“已生成、未验证”，不能声称有 verified 指标；
- mock generator 只用于可信本地夹具，真实候选必须使用 `generator=llm` 与 Docker runner；
- 纯理论证明、创新机理假设和政策价值判断不应强行交给 VES；
- 当前 Skill 只接入回归切片；VES-Modeling 上游已提供 25 类稳定 API（分类、时序、优化、ODE 等），其余切片按 [docs/VES_ADAPTATION_ROADMAP.md](docs/VES_ADAPTATION_ROADMAP.md) 逐步接入。
- 可视化目前为基础模板（统一风格、figure manifest、VES 数据入图门禁与 LaTeX 图路径校验为后续计划，见 [docs/VES_ADAPTATION_ROADMAP.md](docs/VES_ADAPTATION_ROADMAP.md)）。

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
        └── tests/
```

## 许可与来源

本仓库沿用 MIT License。上游 fork 来源、固定 commit、改造点和外部材料边界均在 [`THIRD_PARTY_NOTICES.md`](skills/ves-mathmodel-skill/THIRD_PARTY_NOTICES.md) 中列明。竞赛名称、官方规则、论文、数据集和外部链接仍受各自权利与条款约束。
