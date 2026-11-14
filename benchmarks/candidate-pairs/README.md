# 三类任务的成对运行

使用候选题面的原文运行裸DSH和当前插件配置：P02（只准备输入）、C04（单算例腐蚀计算）、W01（连续与分段续算）。两组都只要求计算和交付，不投放参考答案或评分思路，不作参考解比对。

```sh
python3 -B benchmarks/candidate-pairs/run_suite.py \
  --output runs/candidate-pairs-new \
  --snapshot /absolute/path/to/frozen-plugin
```

输出目录必须尚不存在。模型固定为 `deepseek-official/deepseek-v4-flash`，每会话超时1800秒。每个题目配对各运行一次，六会话共享机器和API；该设计用于观察执行流程，不能据单次耗时断言稳定性能。P02、C04、W01的真实启动上限分别为0、2、4；失败和重试同样计数。

`--preflight-only`只进行配置、启动帮助、文件读取隔离、网格工具、求解器帮助及离线套接字拒绝检查（不建立网络连接），不调用模型生成或进行物理求解。Linux Landlock ABI至少需要3；隔离失败会直接中止，不能退回只靠提示词的限制。

两组均关闭原生网页工具及提供者，采用相同的任务子进程 seccomp 离线执行器；只保留 DSH 宿主模型 API 连接。裸组不加载技能或共享任务协议，离线执行器是共同基础设施。

整个DSH进程和后代均受Landlock允许清单约束。两组只能读取本组数据、必要系统文件和求解器实现；skill组另可读取冻结插件。允许列目录名，但题库、其它组、历史运行、原始带预期值的Allrun及裸组插件文件内容均被禁止。每组使用独立DSH_HOME、追踪、临时目录和缓存。DSH_HOME中的本机认证文件只用于当前机器运行，不在报告中输出。

源输入复制时保留0/、constant/、system/及根输入和生成器；解引用软链。Allrun仅保留计算步骤并传播失败；原验证期望、绘图、清理脚本不投放。各组另有同内容的sources目录用于公开算例接口。原始源库保持不变。

求解包装器不修改求解器，真实执行统一的OFFBEAT二进制。每次启动归档输入、状态哈希和起止快照、逐次原始日志与退出码。帮助查询不计真实启动。独立检查读取这些证据和最终结果场，不以DSH退出码或模型自述代替物理完成。

运行完成后的检查顺序如下；各检查不启动求解器。

```sh
python3 -B benchmarks/candidate-pairs/evaluate_suite.py RUN_ROOT
python3 -B benchmarks/candidate-pairs/check_delivery.py RUN_ROOT
python3 -B benchmarks/candidate-pairs/audit_exposure.py RUN_ROOT
python3 -B benchmarks/fuel-rod-power-ab/summarize_traces.py RUN_ROOT/P02
python3 -B benchmarks/fuel-rod-power-ab/summarize_traces.py RUN_ROOT/C04
python3 -B benchmarks/fuel-rod-power-ab/summarize_traces.py RUN_ROOT/W01
python3 -B benchmarks/candidate-pairs/analyze_suite.py RUN_ROOT
```

最终运行目录另存evaluation检查脚本及reference_reader.py，可离开当前benchmarks目录复核。报告只总结可观察工具和文件行为；原始DSH会话单独保留，不把内部推理正文翻写成过程说明。

首次预跑位于 `runs/candidate-pairs-20261112-01`。该轮被确认有裸组技能读取和题库提示暴露，仅作诊断。02、03分别记录目录遍历权限及DNS软链引起的启动失败，均无求解器运行。修正隔离后的有效实验为 `runs/candidate-pairs-20261112-04`。不可混用各轮耗时或将预跑裸组记作合格裸基线。
