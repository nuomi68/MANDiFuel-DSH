---
name: prepare-offbeat-case
description: 用户要求建立或修改 OFFBEAT 算例、设置载荷历史、材料、几何、边界或空间采样配置时使用；没有源算例时从本地卡片选择参考并评估适用性。交付独立输入与回读，后续求解使用 execute-offbeat-case，多工况研究接入共享 Study。
---

# 准备请求的输入

启动器已经准备受支持环境。先加载所需技能。已有源算例时，直接读取与请求有关的输入卡、被引用的数据和执行配方；不检查安装、动态库或源码目录。本技能只做输入卡准备。只读输入卡、使用说明与必要数据，调用现成编辑器和生成器；禁止查看或修改它们及求解器的实现。使用说明不足时记录缺口，不打开源码兜底。

## `prepare` 类的必经工作流

只要求选型、建模或改输入时命中本类；单算例和研究任务也可调用本技能完成其准备阶段。其他未覆盖任务不继承本工作流。

1. **选源**：复用用户指定且适用的源；没有源时通过下述本地 RAG 入口检索并评估。按题面与源确认基本模型适用性；未覆盖的可选语法与组合允许在一般流程中依据运行反馈补足。
2. **隔离**：在任务工作区复制完整输入，处理软链并保存源路径及沿用假设；已有独立目标直接复用有效证据。
3. **绑定**：定位真实输入所有者和物理依赖；采用公共编辑接口，仅具体语法或能力缺口使用局部代码。
4. **批量修改与回读**：把已确定编辑放在同一脚本，首项回读成功后复用绑定；失败时停止依赖修改，不重复已成功回读。
5. **交接**：目标路径、变更清单、回读和未解决项齐全才完成准备。纯准备任务到此结束；请求求解时将同一目标交给 Execute，研究则提供 `prepare(point)` 给 Study。

以下各节提供每步的具体接口。用户只要求其中一段时，复用已有阶段，不为了走流程重做前置步骤。

## 软件能力表先定位

改卡前按本次意图查[当前安装能力表](references/software-capabilities.md)，可在一次调用中查询多个相关选择器、参数和依赖。已核实的关闭方式与别名直接采用；不能把 none 当通用关闭值。源输入已满足要求时保留，每项修改对应用户要求或必要依赖，不为整理格式截断时间表。

本次改动涉及模型选择器、热边界或时间载荷时，在批量准备脚本末调用 `software_capabilities.check_case(case, source=source)` 并保存准备记录；同一输入已有记录就复用，纯结果提取不做此检查。处理检查结果时：已知错误先修正，未收录/未核实项不等于任务不能执行。接口通过不证明全部物理正确，仍用运行反馈修复未知问题。查询和检查不读实现、不检查安装、不启动求解器。Execute复用该记录，不再把全表变成逐项探索清单。

## 已验证契约优先

请求包含 Cs 常扩散系数且源为单 UO2 区、单 `FpDiffusion` 时，必须使用[参数计划入口](references/parameter-plan.md)，不要重新搜索可疑键名或手写改卡脚本。入口把模型门槛、真实参数绑定、批量修改、回读、已有准备复用和实际场核对固化；任务给定的时间、温度等仍由请求提供。检查不匹配就回到本技能的一般输入工作流，按源、局部说明和运行反馈绑定；专用入口不适用本身不构成停止任务的理由。

## 选择源并隔离目标

用户指定 `source-case/` 时沿用它。需要选源时，读取 `$MANDIFUEL_PLUGIN_ROOT/rag/index/vocabulary.json` 中的 `labels`，由当前主助手将用户需求映射到词表。九个分面涵盖任务意图、系统或部件、燃料或反应堆背景、几何、物理模块、求解特征、载荷、输出和近似算例间的区别。只提交题面支持的值，未限定项留空。不要为了命中某张卡反推题面没有给出的条件。

例如“球对称、内外恒压”可这样查。按本题实际替换查询和标签。

```bash
python3 "$MANDIFUEL_PLUGIN_ROOT/rag/experience/dual_query.py" --query '空心球壳内外恒压 hollow spherical shell internal external pressure' --labels-json '{"geometry":["1D_spherical"],"driving_condition":["constant_pressure"]}' --case-limit 5 --experience-limit 3 --compact
```

查询包含本题中文和对应英文工程关键词，供两个库分别匹配。算例结果 `retrievers.case_rag.output` 中的 `query_mapping.mapped_labels` 和各候选的 `matched_labels`、`score_components` 可核对实际打分。算例侧报标签错误时按词表纠正。经验结果 `retrievers.experience_rag.output.results` 中有短经验、适用背景和相邻条目。两库分别排序。任一侧不可用时保留其状态，继续使用成功的一侧。

保存联合查询结果，检查候选的几何、材料、物理能力与排除条件，再解析配置的只读源库。在交付或选源说明中简述最终源路径及所用经验条目 ID、用途；没有适用经验或没有可映射的标签时如实说明。没有匹配时仅补充本地关键词或标签，本地资料不足就记录缺口，不联网，也不用旧任务答案替代选源证据。

在工作区复制源输入树，默认目标为 `case/`。`0/`、`constant/`、`system/` 与算例根目录模型文件一起保留。复制时处理相对软链；不要修改源库。区分用户要求的变更和沿用的参考假设。确有必要工程信息缺失时再询问。

## 按变更一次读取

同一响应批量读取下表相关项；文件已有上下文时复用。不要先列目录再逐项猜，也不要把每行都执行。

| 本题变更 | 首批读取 | 通常直接保留 |
|---|---|---|
| 只改终点、步长、ASCII 或续算路径 | `system/controlDict`、`constant/solverDict` 的选择器和时间载荷、`Allrun` 或现有运行配方；仅沿其中必要引用补读 | `0/T`、`0/D`、`0/gapGas`、材料、网格、`fvSchemes`、`fvSolution`、`rodDict`、`input_settings.txt` |
| 改尺寸 | 对应生成器参数、相关材料冷态尺寸、执行配方；监测点确需随几何移动时加读其定义 | 其他模型开关、离散和收敛配置 |
| 改温度、功率或压力 | 对应场边界或载荷表、引用该表的输入、时间范围、执行配方 | 不受该载荷影响的初场和几何 |
| 只提取已有结果 | 不在本技能重新准备；交 Extract 使用现有结果根 | 全部源输入 |

复制时保留整套输入及根目录模型文件。未请求改变的输入不因“检查完整性”而重新阅读、归一化或改写。一个文件的多项变更和跨文件物理依赖一次准备；公共编辑器返回的回读直接作为证据。

## 解析输入绑定

从[输入绑定表](references/input-bindings.md)的对应项定位实际输入所有者，沿所选模型、`#include` 和 `file` 引用查找定义文件。已知的独立输入可在同一响应中批量读取。单纯载荷变化复用现有几何；半径、直径、厚度或间隙变化同时检查材料冷态尺寸等物理依赖。

| 几何来源或变更 | 应读参考 |
|---|---|
| `rodDict`、`rod3Ddict.json` 或 `sphereDict` 管理的尺寸 | [生成器尺寸](references/radial-geometry.md) |
| 无生成器的显式径向坐标，或另行请求的保留坐标 | [径向坐标映射](references/radial-coordinate-map.md) |
| 箱体尺寸、网格宽度 | [箱体缩放](references/box-geometry.md) |
| 扇区角度或 UNV 节点 | [角度映射](references/sector-geometry.md) |
| 现有结构不能表达请求的新燃料棒 | [几何构建](references/geometry-construction.md) |

## 优先使用现成编辑接口

OpenFOAM 中已有字典项使用公共编辑器：

```bash
python3 "$MANDIFUEL_PLUGIN_ROOT/skills/prepare-offbeat-case/scripts/foam_edit.py" --case ./case --file system/controlDict --entry startFrom --set startTime
python3 "$MANDIFUEL_PLUGIN_ROOT/skills/prepare-offbeat-case/scripts/foam_edit.py" --case ./case --file constant/solverDict --entry heatSourceOptions/lhgr --set '(0 18000 18000)'
```

`--entry` 是文件内部的字典路径，不重复文件名，例如 `startFrom`，不是 `controlDict/startFrom`。多行值使用 `--set-file`；不传设置选项时仅回读。包含文件在其定义处编辑，避免展开无关宏。

Python 批量编辑使用以下接口；返回记录已经包含原生回读的 `value`，无需查看辅助程序源码或再调用一次读取：

```python
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['MANDIFUEL_PLUGIN_ROOT']) /
                       'skills/prepare-offbeat-case/scripts'))
from foam_edit import get_foam_entry, set_foam_entry

case = Path('case')
edits = [set_foam_entry(case, 'system/controlDict', 'endTime', '100'),
         set_foam_entry(case, 'system/controlDict', 'deltaT', '1')]
# 每项为 {'file': ..., 'entry': ..., 'value': 回读字符串}。
# 只读：get_foam_entry(case, file, entry) -> str。
```

示例数值替换为用户要求；路径与条目先按当前输入绑定。坐标操作使用 `geometry_ops.apply`。生成器的 Python 字面量参数、裸列表、新增条目或确需保留原文字节的内容使用有针对性的任务代码。已有接口支持的字典替换不另写正则编辑器；确需替代时记录不支持的语法或格式要求。

将已解析的多项编辑、逐项回读及准备记录放在同一脚本调用中。首项请求修改成功后再复用绑定，同一文件顺序写入，前置失败时停止其依赖项。原生返回已包含回读，无矛盾时不再逐项读一遍。

## 运行反馈触发的输入修复

执行阶段发现可修复输入错误时，复用已有源选择、用户参数和准备脚本，只定位错误关联项与依赖，批量修复并回读，交给 Execute 在新尝试目录重新求解。旧失败证据保留；新鲜初态或续算检查点从可信输入取得。默认不设启动次数上限，流程见[输入恢复](../execute-offbeat-case/references/input-recovery.md)。不能只因没有现成契约或此前失败次数而提前交付。

## 准备交付

交付目标路径、变更清单、原生回读或任务局部修改后的精度一致回读，以及沿用的参考设置。几何返回的 `validation.status == 'passed'` 只证明该操作覆盖的变更。发生差异时只回到对应绑定。

已有生成器且执行配方会调用它时，参数修改即完成对应准备；只有用户要求网格字典交付时提前生成字典。预处理由执行配方负责，避免多处重复生成网格。多工况把同一绑定封装为 `prepare(point)`，由 Study 传入各点和独立目标，加载 Orchestrate 与 Conduct 完成配置和执行。
