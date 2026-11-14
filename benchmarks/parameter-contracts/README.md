# 固化参数与重复操作试验

已实现单 UO2 / FpDiffusion / Cs 常扩散参数契约和公共参数计划入口。准备、执行及提取三个 Skill 复用这一入口；相同准备证据可复用，实际生效独立核对，不用猜键和追加诊断求解。

- [本次对比报告](../../runs/parameter-plan-c06-20261114-02/固化操作对比.md)：C06 原题，修复后 136.483 秒、21 次工具调用、1 次真实 OFFBEAT 启动，正确完成。
- [修复后中文单行轨迹](../../runs/parameter-plan-c06-20261114-02/中文单行轨迹/C06_Skill_一行轨迹.md)：21 行。
- [首次联调轨迹](../../runs/parameter-plan-c06-20261114-01/中文单行轨迹/C06_Skill_一行轨迹.md)：36 行，保留相对路径缺陷和恢复过程。
- [公共入口说明](../../skills/prepare-offbeat-case/references/parameter-plan.md)、[参数契约](../../skills/prepare-offbeat-case/assets/parameter-contracts.json)。
- [验证记录](validation.json)：23 项通过，无额外 OFFBEAT 启动；[测试脚本](../direct-execution/check_parameter_plan.py)。
- [试验设计](experiment-design-v2.json)、[报告生成器](report_c06.py)。报告生成器只读取证据，不启动模型或求解器。

原 Skill 的 54 次工具调用没有正确绑定 D；已有裸组正确完成，用时 557.153 秒、173 次工具调用。当前只是一题的跨轮观察，写出频率也有自主选择差异。后续应以新 D、温度和新案例验证迁移，再扩展其他有证据的契约。

继续压缩的目标：复用入口返回摘要，收拢末尾重复读卡、日志查看和报告脚本的文字修正。固化知识要有适用门槛和真实场验证，不把未经验证的猜测做成默认操作。
