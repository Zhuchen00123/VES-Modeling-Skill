# 2022 CUMCM E题「小批量物料的生产安排」端到端测试方案与提示词

---

## 1. 测试目标与定位

本测试旨在全面检验 **VES-Modeling-Skill**（数学建模协作工作流）与 **VES-Modeling / CES 计算引擎**的端到端实战能力。
通过对 2022 年全国大学生数学建模竞赛（CUMCM）E 题「小批量物料的生产安排」进行全流程建模、计算搜索、独立验证与论文排版，产出一篇符合国赛一等奖标准的完整高质量 LaTeX 论文与最终 PDF 产物。

---

## 2. LLM 与 DeepSeek Harness 配置指南

### 2.1 阿里 Token Plan（千问平台）API 接口信息
- **平台控制台**：[阿里云百炼 / 千问平台 API Keys](https://platform.qianwenai.com/home/api-keys)
- **Token Plan 专属 API Key**：`***REMOVED***`
- **OpenAI 兼容 Base URL**：`https://coding.dashscope.aliyuncs.com/v1`
- **Anthropic 兼容 Base URL**：`https://coding.dashscope.aliyuncs.com/apps/anthropic/v1`
- **测试模型 ID**：`deepseekv4flash0731`（或 `deepseek-v4-flash-0731` / `deepseek-v3`）
- *注：Token Plan 的 `sk-sp-` 密钥为专用端点鉴权凭证，若调用返回 401 请在平台控制台检查订阅状态与额度。*

### 2.2 DeepSeek Harness Preset 选型
- **推荐 Preset**：**`standard`（标准模式）**
  - **推荐理由**：`standard` Preset 提供完整的文件读写、跨平台 Shell 交互、Docker 容器调度、子代理编排与状态持久化能力，与数学建模 10 阶段的生命周期最为契合。

---

## 3. 核心运行环境与工具链路径

| 组件 | 路径 / 配置 | 说明 |
| :--- | :--- | :--- |
| **Python 运行环境** | `C:\Miniconda\envs\mineru\python.exe` | 已安装 numpy 2.4+, pandas 3.0+, scipy, scikit-learn, seaborn, matplotlib, openpyxl, unidiff 等 |
| **LaTeX 引擎** | `C:\texlive\2026\bin\windows\xelatex.exe` | TeX Live 2026，已实测验证支持 `ctexart.cls` 及中文字体 |
| **Pandoc 转换器** | `C:\Users\15185\AppData\Local\Pandoc\pandoc.exe` | Markdown 到 LaTeX 结构化转换引擎 |
| **Docker 容器环境** | `ves-modeling-runner:0.1` | Docker Desktop Engine 已启动，用于隔离执行不可信代码与宿主验证 |
| **VES 计算引擎** | `F:\codexprojects\VES-Modeling` | 包含 25 个 Vertical Slice（forecasting, optimization, multiobjective 等） |
| **VES Core 核心** | `F:\codexprojects\aide_change` | 提供可验证搜索、六态 AttemptStatus 与判定管线 |
| **VES 子问题注册脚手架** | `F:\codexprojects\VES-Modeling-Skill\skills\ves-mathmodel-skill\scripts\ves_scaffold.py` | Stage 2/3 一键注册切片、创建数据目录并生成执行指令 |
| **VES 回归/通用适配器** | `F:\codexprojects\VES-Modeling-Skill\skills\ves-mathmodel-skill\scripts\run_ves_problem.py` | 25 类通用切片可验证搜索与调度器 |
| **VES 实验报告生成器** | `F:\codexprojects\VES-Modeling-Skill\skills\ves-mathmodel-skill\scripts\render_ves_report.py` | 自动生成实验报告 Markdown/LaTeX 并同步至 decision_log |
| **论文渲染脚本** | `F:\codexprojects\VES-Modeling-Skill\skills\ves-mathmodel-skill\scripts\render_paper.py` | 论文分节组装、占位符检查、VES 门禁与三编 XeLaTeX |
| **图表工具** | `F:\codexprojects\VES-Modeling-Skill\skills\ves-mathmodel-skill\tools\figure\` | 出版级图表规范与可视化导出脚本 |

---

## 4. 题目与输入数据路径

- **题目描述 PDF**：`F:\codexprojects\VES-Modeling-Skill\problem\2022E\E题.pdf`
- **历史需求数据**：`F:\codexprojects\VES-Modeling-Skill\problem\2022E\附件.xlsx`
  - 数据规模：2019-01-02 至 2022 年共 22,453 条订单记录。
  - 数据字段：`日期`、`物料编码`、`需求量`、`销售单价`。

---

## 5. 严苛边界与防偷懒/防伪造红线

1. **绝对防泄漏红线**：
   - 外部参考标准答案路径（`F:\mineru\output\1693143223386` 和 `F:\mineru\output\1693143247091 (1)`）为评测对照基准，**严禁将该路径或其任何内容作为 prompt、背景上下文、注释或代码输入注入给模型**。
   - 整个求解过程必须为 100% 盲测建模。
2. **强制使用 VES 引擎（禁止随意声明 `out_of_ves_scope`）**：
   - 凡属于 VES 25 切片范畴（如 Q1 周预测对应 `forecasting`，Q2/Q3 排产与库存优化对应 `optimization` / `multiobjective`），**必须调用 `scripts/run_ves_problem.py` 或 `scripts/run_ves_regression.py`** 产生真实 `manifest`。
   - 严禁借口“时序耦合状态机”等理由绕过 VES。只有纯定性理论综述才允许声明 `out_of_ves_scope`。
   - 严禁在本地 Python 脚本中自跑自报未经宿主 verified 的指标。
3. **物理门禁阻断（Fail-Closed Gate Checks）**：
   - Stage 5 评分与 Stage 8 论文组装时，`score_artifact.py` 与 `render_paper.py` 会自动扫描 `decision_log` 与磁盘上的 `manifest_path`。若缺失真实生成的 verified manifest，将被直接阻断。
4. **CUMCM 竞赛格式规范**：
   - 摘要为一页纸独立结构，包含问题、模型方法、关键结果与创新点；
   - 必须通过 42 项反模式审计（`anti_patterns.md`）。

---

## 6. 题目四大核心问题与 VES 对接极简操作流

### 步骤 1：Stage 2/3 自动注册子问题到对应切片
```bash
# 注册 Q1 周预测到 forecasting 切片并创建数据目录脚手架
python skills/ves-mathmodel-skill/scripts/ves_scaffold.py \
  --register --qi Q1 --slice forecasting --description "重点物料周需求量多步预测" --create-dirs

# 注册 Q2 生产排产到 optimization 切片
python skills/ves-mathmodel-skill/scripts/ves_scaffold.py \
  --register --qi Q2 --slice optimization --description "服务水平>=85%滚动排产优化" --create-dirs
```

### 步骤 2：Stage 5 运行 VES 进行搜索与宿主独立验证
```bash
# 执行 Q1 周预测可验证搜索
python skills/ves-mathmodel-skill/scripts/run_ves_problem.py \
  --slice forecasting \
  --public-dir data/q1_public \
  --host-dir data/q1_host \
  --workspace ves_runs/q1_forecasting \
  --output state/q1_manifest.json
```

### 步骤 3：Stage 5 生成规范实验报告并同步状态
```bash
# 一键生成 Markdown 实验报告并同步 verified 指标至 decision_log
python skills/ves-mathmodel-skill/scripts/render_ves_report.py \
  --manifest state/q1_manifest.json --qi Q1
```

### 步骤 4：Stage 8/9 论文引用与编译
- 论文正文直接引用 `results/Q1_ves_report.md` 中的指标与表格。
- 调用 `python skills/ves-mathmodel-skill/scripts/render_paper.py --competition cumcm --workspace paper_workspace/` 完成 XeLaTeX 三编生成最终 PDF。

---

## 7. 测试启动 Prompt（直接复制使用）

```markdown
请作为参加全国大学生数学建模竞赛（CUMCM）的特等奖队伍，加载并严格遵循 `ves-mathmodel-skill` 工作流，完成 2022 年国赛 E 题「小批量物料的生产安排」的完整端到端建模求解与 LaTeX 论文排版。

【输入文件】
- 题目描述：F:\codexprojects\VES-Modeling-Skill\problem\2022E\E题.pdf
- 附件数据：F:\codexprojects\VES-Modeling-Skill\problem\2022E\附件.xlsx

【执行要求】
1. 竞赛类型：CUMCM（全国大学生数学建模竞赛）。
2. 状态维护：自动在 `<cwd>/state/decision_log.json` 中完整记录 Stage 0 到 Stage 9 的决策与指标。
3. 严格遵循 VES 可验证计算（使用脚手架与实验报告工具）：
   - 在 Stage 2/3 使用 `scripts/ves_scaffold.py` 注册子问题到对应切片（Q1 绑定 `forecasting`，Q2/Q3 绑定 `optimization`/`multiobjective`）；
   - 在 Stage 5 运行 `scripts/run_ves_problem.py` 完成搜索并由 Verifier 独立评定指标；
   - 运行 `scripts/render_ves_report.py` 生成规范实验报告（`results/<Qi>_ves_report.md`）并自动同步回 `decision_log`；
   - 严禁随意声明 `out_of_ves_scope` 或自报未验证数据，论文指标必须严格绑定真实生成的 verified manifest。
4. 计算与表格产出：
   - 基于附件 22453 条订单真实计算，产出正文表 1（101~110 周明细）与正文表 2（101~177 周全期汇总），并导出 `支撑材料.xlsx`。
5. 图表规范：
   - 使用 `tools/figure/scripts/setup_style.py` 统一配色与字体，生成物料分类分布图、预测对比曲线图、库存/缺货动态时序图、帕累托权衡前沿图等出版级矢量图（PDF/PNG）。
6. 论文产出与合规编译：
   - 编写包含高质量一页纸摘要、符号说明表、假设体系、问题 1~4 详细建模与求解、灵敏度分析、模型评价及参考文献的 10 节 Markdown。
   - 调用 `scripts/render_paper.py` 并通过 XeLaTeX 编译生成最终高质量参赛论文 PDF。
   - 严格通过 `anti_patterns.md` 中的 42 项反模式自查，确保无虚假自报指标、无未定义符号、无格式缺陷。
```
