# 20 题 DSH 后端配对评测

同一工程题分别交给 DSH 基线、项目 Skill 和 Skill + 审核经验库。每个会话有独立的题目输入副本、工具轨迹、求解目录和交付文件。三组均从 `headless` 入口运行，关闭展示插件和 Web 工具。

## 复核已有实验

在仓库根目录执行以下命令可重新读取原始会话并评分。评分、导表和绘图都使用本地文件。

```sh
cohort=runs/three-arm-20-20261119-01
dest=output/20题三组后端对照
python3 -B benchmarks/three-arm-20/analyze.py "$cohort"
python3 -B benchmarks/three-arm-20/export.py "$cohort" "$dest"
/home/lwz/micromamba/envs/fenicsx/bin/python benchmarks/three-arm-20/figure.py "$cohort" "$dest/后端用量对照.png" --font frontend/assets/fonts/workbench-cjk.ttf
```

## 在同一环境另起一轮

创建一个新的批次目录需要仓库现有的 DSH 登录、OpenFOAM、OFFBEAT，以及 `tasks.py` 列出的 16 份原始数据。运行器使用 `benchmarks/token-pairs-20261117` 中的启动与隔离程序。以下第一条 Python 命令会实际发起 60 个付费模型会话。第二条运行 8 次独立求解来复现参考值。

```sh
cohort=runs/three-arm-20-repeat-02
python3 -B benchmarks/three-arm-20/run.py "$cohort" --workers 15 --timeout 1200
python3 -B benchmarks/three-arm-20/calibrate.py "$cohort"
python3 -B benchmarks/three-arm-20/analyze.py "$cohort"
```

题面、单位、来源和分组见 `tasks.py`，参考值计算见 `reference.py`。批次根目录的 `manifest.json` 保存随机次序、模型、题目清单、阈值、版本及文件指纹。`definition/` 保留运行时的定义。`reference.json` 和 `calibration.json` 分别保存盲评参考和独立重跑值。每次运行的 `run.json`、`traces/`、`workspace/answer.json` 与求解日志可用于复查。

每题计两个数值。任务成功检查交付、输入、工具执行和求解终点。物理符合还要求两个数值均在 `max(0.005 × |参考值|, 1e-12)` 范围内，分母包含所有分配到该组的题。明细同时列出逐项数值命中及独立复读终态场的结果，便于区分数值偏离和工况终点偏离。
