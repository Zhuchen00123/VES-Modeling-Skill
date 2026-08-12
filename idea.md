# VES-MathModeling-Skill 开发提示词

## 项目目标

构建一个增强型数学建模 Skill。

目标不是重新发明一个数学建模 Agent，而是：

> 使用成熟数学建模工作流作为外壳，结合 VES-Modeling 作为可信计算核心，形成一个更可靠的数学建模助手。

整体架构：

```
数学建模 Workflow
        |
        |
        ↓
VES-MathModeling-Skill
        |
        |
        ├── 题目理解
        ├── 子问题拆解
        ├── 模型选择
        ├── 结果解释
        ├── 论文组织
        |
        ↓
VES-Modeling
        |
        |
        ├── 候选模型生成
        ├── 可执行代码搜索
        ├── 实际运行
        ├── 独立验证
        ├── 结果比较
        └── 最优方案选择
```

---

# 核心设计原则

## 1. VES-Modeling 是计算核心

所有适合自动搜索和验证的计算建模任务，应优先考虑使用 VES-Modeling。

例如：

- 回归预测；
- 参数优化；
- 数据驱动模型选择；
- 可验证的机器学习建模；
- 需要大量实验比较的问题。

不要让 Agent 直接相信：

- 自己生成代码后的自报结果；
- 自己描述的模型效果；
- 没有实际运行验证的结论。

优先使用：

```
生成候选
    ↓
实际执行
    ↓
独立验证
    ↓
Evidence
    ↓
选择方案
```

这也是 VES 的核心价值。

---

# 2. 不要把 VES 当成万能工具

数学建模任务具有开放性。

不要强迫所有问题使用 VES。

应该根据问题判断：

适合：

```
数据预测
模型比较
参数搜索
算法选择
实验验证
```

优先调用 VES。

不适合：

```
纯理论证明
复杂数学推导
创新机理建模
需要人工判断的假设设计
```

可以使用普通数学建模流程。

目标：

> 让 VES 增强数学建模能力，而不是限制数学建模思考。

---

# 3. 外层 Workflow 可以借鉴和改造优秀 Skill

不要从零开始设计完整数学建模流程。

允许：

- 研究优秀数学建模 Skill；
- fork 合适项目；
- 参考成熟 Agent 工作流；
- 修改角色划分；
- 增加 VES integration。

重点关注：

- 如何读题；
- 如何拆分问题；
- 如何组织建模思路；
- 如何生成代码；
- 如何整理结果；
- 如何生成论文。

外层可以自由演化。

---

# 4. 保持核心边界

不要复制 VES-Modeling 内部实现。

VES-MathModeling-Skill 负责：

```
What should we solve?
Why solve this way?
How explain the result?
```

VES-Modeling 负责：

```
Which executable solution works better?
```

不要重新实现：

- Verifier；
- Judge；
- SearchEngine；
- Candidate execution；
- Evidence generation。

这些属于 VES。

---

# 5. 第一阶段目标

不要追求完整自动化数学建模比赛。

先完成：

```
数学建模题
    ↓
识别子问题
    ↓
判断是否适合 VES
    ↓
调用 VES-Modeling
    ↓
获得可信结果
    ↓
继续分析和表达
```

优先支持：

```
Regression / Prediction
```

因为 VES 当前已经具备这一能力。

---

# 6. 第一版不要过度工程化

不要提前设计：

- UniversalModelingTask；
- Plugin 大系统；
- 全领域 Solver Registry；
- 复杂 Agent 调度框架。

先让真实案例推动设计。

优先：

简单流程

↓

真实使用

↓

发现问题

↓

增加能力

---

# 7. 推荐开发方式

## Phase 1：寻找优秀外壳

研究已有数学建模 Skill：

重点看：

- 工作流设计；
- Agent 角色；
- Prompt 结构；
- 输出组织。

选择一个基础版本。

---

## Phase 2：加入 VES Adapter

增加：

```
Math Modeling Task
        ↓
Computational Subproblem
        ↓
VES Adapter
        ↓
VES-Modeling
        ↓
Verified Result
```

第一版只支持：

```
regression
```

---

## Phase 3：真实案例测试

选择数学建模题中的一个计算子问题。

测试：

```
题目分析
 ↓
模型设计
 ↓
VES计算
 ↓
结果分析
 ↓
论文素材
```

观察：

- VES 是否提升效果；
- Workflow 是否合理；
- 哪些能力需要补充。

---

# 8. 输出要求

开发过程中优先保持：

代码简单；

接口清晰；

方便修改。

每次增加功能回答：

```
这是 Workflow 问题？
还是 VES Core 问题？
```

如果属于：

```
智能决策
题目理解
论文表达
流程管理
```

放 VES-MathModeling-Skill。

如果属于：

```
执行
验证
搜索
候选比较
可信实验
```

放 VES-Modeling。

---

# 最终目标

形成：

```
优秀数学建模 Skill
        +
VES-Modeling可信计算引擎
        +
LLM智能决策能力
```

成为一个：

既能像数学建模专家一样思考，

又能像实验平台一样验证结果的数学建模 Agent。

保持开放探索，不要过早限制模型发挥空间。
