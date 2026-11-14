---
name: orchestrate-offbeat-study
description: 为 OFFBEAT 固定点扫描、有限候选、概率采样、不确定性传播、自适应优化或反演配置分类工作流。研究控制器编写前必须与 conduct-offbeat-study 一起加载，使用共享 Study；仅单算例执行或已有结果分析使用相应原子技能。
---

# 按分类配置研究

沿用启动器已准备的环境与工具入口；任务代码只负责点表、输入卡和响应。先按公开签名配置控制器，不检查安装、动态库或逐层读取 Study、求解器和解析器实现。研究配置仍属输入卡驱动的运行工作。禁止查看或修改共享库、算法库和求解器实现；具体调用出错只查输入、日志和接口说明，仍缺能力就报告，不临时重写工具。

## 分类与必需入口

本技能负责 `fixed-study`、`sampling-study`、`adaptive-study` 的配置。命中后按下表执行；不会把概念解释、仓库开发或其他未覆盖任务纳入研究工作流。

编写控制器前必须通过 DSH 的 `skill` 工具加载 `conduct-offbeat-study`，并读取其[公共接口](../conduct-offbeat-study/references/study-runner.md)。已注入完整内容时复用，链接不等于加载。按缺口加载 Prepare、Execute、Extract；完整评价器可以直接适配，不重复准备其已覆盖的阶段。

| 分类 | 判断依据 | 必须读取的方法参考 | 必须保留的配置 |
|---|---|---|---|
| `fixed-study` | 全部点可预列，无概率设计或反馈更新要求 | [固定扫描与候选](../conduct-offbeat-study/references/sweeps-and-candidates.md) | 完整有序点表、身份、共同物理情景、比较或排序规则 |
| `sampling-study` | 固定概率或结构化抽样设计 | [不确定性](../conduct-offbeat-study/references/uncertainty-quantification.md) | 联合输入定义、生成器与种子、数值样本表、块结构及估计器 |
| `adaptive-study` | 后续点依赖已有响应，或需保持搜索算法的生命周期 | [自适应优化与反演](../conduct-offbeat-study/references/optimization.md) | 原生方法、参数与约束、初始化、更新及停止规则、可恢复状态 |

有限候选选最优仍是固定点研究。只有范围没有概率模型时，不以不确定性量化名义输出概率结论。响应驱动采样归自适应研究，并同时采用其概率设计约束。用户仅要求配置时，在交付配置后停止，不自行求解。

## 三类共用的配置阶段

公共选择器和输入所有者先按[软件能力表](../prepare-offbeat-case/references/software-capabilities.md)定位；多点复用共同的能力查询，在每点准备脚本中只检查变化及直接依赖。未覆盖模型保持一般流程，不按题号或熟悉程度阻断。

1. 在现有计划或定义文件记录分类和依据。固定源、独立参数、单位和物理依赖，采用用户指定方法；未指定时选择并记录适合问题和预算的具名方法。
2. 没有源算例时必须先由 Prepare 通过 RAG 选型并评估。并发在执行前确定；默认无真实启动次数上限，只有用户明确限制时才设置。固定方法的请求点数和停止条件保留；诊断修复不额外改变物理研究设计。
3. 明确每项响应的对象、范围、时间、分量、归约和单位。区分方法需要的 `progress` 与最终报告需要的 `reporting`，纯报告响应集中收集。
4. 将输入绑定、准备和提取接入公共 API。已知接口和输入所有者批量读取；首项修改成功回读后复用绑定。任务局部脚本只负责输入卡、公共调用和数据汇总；公共工具不支持的能力明确报告，不查看或替换其实现。
5. 按本类方法参考完成点表或算法配置后，交给 Conduct 运行。控制器、执行路径和所需响应尚未配置完整时不能进入求解阶段。

涉及几何、载荷历史和物理耦合时，读取[燃料棒设计约定](../conduct-offbeat-study/references/fuel-rod-design-studies.md)，不加载无关方法参考。

## 固定点与物化样本的必经执行入口

标准 `prepare(point)` 加报告提取的绑定，必须将 `assets/fixed_study.py` 复制为任务工作区的 `study.py`，编写同目录 `study_definition.py`。已有基于共享 Study 的控制器直接复用，不重复复制。

| 名称 | 含义 |
|---|---|
| `POINTS` | 执行前保存的完整参数字典列表；稳定身份、独立目标目录；抽样任务直接使用已物化样本 |
| `prepare(point)` | 修改输入并保存回读，返回独立算例路径 |
| `extract_reporting(result_root)` | 从正常完成结果返回所需响应映射 |
| `WORKERS` | 用户允许的并发数，省略为1 |
| `COMMAND` | 已确认的执行配方，省略为 `['bash', 'run.sh']` |
| `write_report(history)` | 需要产物时定义，使用保留响应集中生成 |

```bash
cp "$MANDIFUEL_PLUGIN_ROOT/skills/orchestrate-offbeat-study/assets/fixed_study.py" ./study.py
python3 study.py
```

模板调用共享 `Study.run` 和 `Study.collect`，保留 `history.json` 和 `study-summary.json`。不要改写成另一套逐点调度、去重或完成判断。模板保持历史幂等；模型发现输入错误后按恢复闭环用新尝试身份继续，不原样自动重试。实际启动保留计数，默认不设上限。完整绑定示例见[定义文件](../conduct-offbeat-study/references/study-runner.md#固定扫描定义文件)。

模板不能表达已提供的完整评价器或特殊执行需求时，记录差异，用 `Study(ROOT, evaluate=evaluate)` 或 `execute=` 接入；仍一次提交完整点表并集中收集，不绕过共享历史。

## 自适应研究的必经执行入口

采用原生算法实例，经 Study 评价候选，或通过 `next_points(history)` 提供就绪集合。已有完整评价器同样用 `evaluate=` 接入。一个算法生命周期由一个 Python 控制器负责，长任务首次即用原生后台方式提交并等待，不能在模型轮次之间逐点重建算法。

顺序单目标 Optuna 且公共接口适用时，必须用 `study_runner.run_optuna`；其他方法保留其原生循环和状态。单点顺序依赖使用一个 worker，批次方法遵守声明的更新边界。每个观测只消费一次，方法结束或中断时保存最后观测、停止原因与原生状态。

## 配置交接与完成条件

交接的是已配置的控制器、点表或方法状态、输入及响应绑定、执行配方、并发与用户明确限制，不能只交接文字建议。Conduct 复用这些配置。固定点完整性、样本设计合法性或自适应方法状态不满足要求时，先修复配置；真实环境或接口阻塞则交付明确的未完成状态，不改标未覆盖任务。
