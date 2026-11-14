# KTH PWR燃料棒解析题：skill与裸DSH对照

题目来自 KTH 的 Henryk Anglart《Applied Reactor Technology》（2011）例4-2，书页103–104，PDF页109–110。公开原文：[DiVA PDF](https://www.diva-portal.org/smash/get/diva2%3A500610/fulltext01.pdf)。这是恒定物性、稳态径向导热的教学解析验证题，有燃料、气隙、包壳、对流四段温差和线功率上限答案；不将它称为辐照实验验证。

`task.txt`只给物理输入和统一交付要求，不给参考答案。三档网格改变数值离散而保持物理条件固定。两组均使用官方OFFBEAT热学算例作为只读骨架；模型自行决定输入、气隙表达、执行和提取。

## 运行和复核

本机复现命令：

```bash
python3 -B benchmarks/kth-fuel-rod-ab/run_ab.py --output "$PWD/runs/kth-fuel-rod-ab-new" --timeout 1800
python3 -B benchmarks/fuel-rod-power-ab/summarize_traces.py runs/kth-fuel-rod-ab-new
python3 -B benchmarks/kth-fuel-rod-ab/verify_results.py runs/kth-fuel-rod-ab-new
```

运行器使用当前实验预先打包的 `/tmp/mandifuel-workflow-routing-final-20261112/mandifuel-plugin-0.4.0-alpha.8`，复制到运行目录的 `frozen-plugin/`，并补入本机 `configs/launcher.env`。换机器需按本机路径调整入口和OFFBEAT位置。原始PDF先下载到 `/tmp/kth-applied-reactor-technology.pdf`；本次已保存到实际运行目录的 `references/`。`reference-values.json`也需保留或从本次归档复制到新的运行目录，评分资料不放入两组工作区。

## 对照条件

- 同一题面、输入骨架、模型 `deepseek-official/deepseek-v4-flash` 和数值软件；两个隔离DSH会话同时运行，每组内部串行求解。
- 裸组禁用技能发现及技能工具，不注入领域协议；skill组通过现有启动器加载冻结的当前协议与五项技能。
- 无历史轨迹、无参考数值注入；提供相同源算例，因此不评价在线RAG选型。
- 两组的透明包装器均调用同一原OFFBEAT二进制，记录启动、退出码及耗时，真实启动上限5次；帮助查询另列。包装器的预算、帮助豁免、失败退出码逻辑用受控替身检查，未额外试跑物理题。
- 原始DSH会话、标准输出和错误保留；中文过程说明只总结可观察操作、证据与恢复，不复写模型内部推理正文。

## 独立数值核对

评分程序不导入任何被测MANDiFuel模块。沿用已有基准的ASCII词法/字典读者，并独立读取网格、场与cellZone；用凸多面体四面体分解计算单元体积和质心。长方体几何、标量场展开和径向拟合经过检查；在实际算例上，重建半径与OpenFOAM写出的C场交叉验证。

独立读者从燃料全区T对r²拟合中心线，从相邻单元及各自导热系数重构内部界面温度，直接读取包壳外边界温度。不同合理外推不要求逐位相等：单元最大值和外边界按写出精度核对，其余温度保留重构差异。评分同时核对实际退出码、End、终点场、输入几何与物性、热源、边界、网格数，以及教材参考误差。薄楔形以平面离散曲面产生的O(角度²)几何差异单独记录。

预设比较阈值存于运行目录的 `references/reference-values.json`，在读取两组最终数值之前保存。阈值是本次数值检查设置，不是实验误差或实际设计限值。教材已四舍五入答案与独立按题目条件计算的完整精度参考分别保留。

只做一次配对，墙钟时间包含模型、读写、准备、求解和报告，不能据此推断普遍加速比。应同时看参考误差、正常完成数、实际启动数、工具/轮次，以及是否真正采用共享Study。
