# 燃料棒线功率扫描：裸 DSH / MANDiFuel skill 对照

题面见 `task.txt`。同一个官方燃料棒热学算例，分别在 10、20、30 kW/m 下进行稳态求解，提取终态两个材料 cellZone 的最高温度并交付数据、曲线和报告。

## 运行

沿用仓库 `configs/launcher.env`、`scripts/prepare-agent.sh` 和 `scripts/start-dsh.sh` 的环境配置。DSH 使用其本地凭据库；本题提供源算例，不需要在线 RAG。

```bash
python3 -B benchmarks/fuel-rod-power-ab/run_ab.py \
  --output "$PWD/runs/fuel-rod-ab-new" --timeout 1200
python3 -B benchmarks/fuel-rod-power-ab/summarize_traces.py runs/fuel-rod-ab-new
python3 -B benchmarks/fuel-rod-power-ab/verify_results.py \
  --run-root runs/fuel-rod-ab-new
```

输出目录必须尚不存在。两组并行启动，每组内部串行执行三个工况。超时会终止该组进程组，原始日志仍保留。

## 对照条件

- 相同题面、源算例、DSH headless、模型 `deepseek-official/deepseek-v4-flash`、Python 和 OpenFOAM 环境。
- 裸组禁用 `skill-filesystem` 与 `tool-skill`，不注入 Study Protocol。
- skill 组通过原有 `start-dsh.sh` 加载当前五项 skill 与 Study Protocol。
- 相同 workspace-write 沙箱和 DSH 默认审批策略；不同工作目录、会话目录及缓存目录。
- OFFBEAT 包装入口记录调用后直接执行原二进制，不改变数值计算。帮助/版本查询单独标记，不计入实际求解次数。
- 当前包装入口和题面中的机器路径来自本机配置；换机器时需同步修改。若模型绕过 PATH 直接调用原二进制，须结合完整工具轨迹核查实际启动次数。

## 产物与评价

`bare/`、`skill/` 各保存 `run.json`、标准输出/错误、完整 DSH JSONL 会话与 `workspace/` 计算结果。`trace-summary.json` 和 `flow-trace.md` 只汇总可观察工具动作、步骤和用量，不导出推理正文。

`verify_results.py` 独立用标准库解析保留的 `1/T` 与 `constant/polyMesh/cellZones`，不调用被测 skill 的提取实现。它核对输入、三次实际求解、终态证据、JSON/CSV 与场数据、两组对应温度和三点近似线性。容差依据实际场写出精度，不代表网格离散误差。

工具调用数包含 skill 加载，另按工具名称分项；工具失败数只统计工具返回的错误/非零退出码，不把最终交付不合格混入。模型用量累加 `assistant/message` 的 usage，缓存命中输入另列；不能直接用总 token 推算费用。墙钟时间包括模型、工具和启动开销，双组同时运行会共享机器资源。

这是一次配对功能基准，不评价 RAG 自动选型，也不能单凭一次运行推断普遍加速比。应结合完整性、正确性、额外探索、接口使用、错误恢复和交付可追溯性分析结果。
