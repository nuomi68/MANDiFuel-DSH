# 从 20 道已核验任务提炼经验卡

## 仅补 C 组：Skill + 可追溯的 20 张新卡

`runs/learned-cards-20-20261119-01` 只新增 20 个独立模型会话，每题一次。A（原 DSH）和 B（Skill）沿用 `runs/three-arm-20-20261119-01` 的已有单次结果。C 从同一历史冻结插件构建，全部共享 Skill 软件与 B 逐文件一致，仅额外启用当时固定的检索提示和 K21–K40 独立经验库。默认合并库不参与，项目默认配置不因本实验改变。

卡片由 `materials.cards()` 从核验记录重建，逐字节对照此前审核的 20 卡语料、索引及来源指纹。插件移除旧审核文件，语料严格限定 20 个父条目及 20 个方法子条目；运行前实际探测旧库、默认合并库和历史答案不可读。全部预检完成后才发起模型会话。

```sh
cohort=runs/learned-cards-20-repeat-02
python3 -B benchmarks/experience-card-transfer/rerun.py "$cohort" --library learned20 --workers 15 --timeout 1200
```

该批次复用原批次已独立求解并核验的裁判校准，保留 `calibration-provenance.json` 的逐文件指纹；评分另外复读 C 的真实结果场。参考校准也可用 `benchmarks/three-arm-20/calibrate.py` 独立重算，但原题输入相同不要求再次求解裁判案例。评分和整体导表：

```sh
python3 -B benchmarks/experience-card-transfer/rerun_score.py runs/learned-cards-20-20261119-01 output/20题方法卡C组补充
```

报告只对比 A/B/C 的整体结果及执行用量，不纳入旧库组或合并库组。原 20 题同时是经验来源题，所以这轮属于原题回归，不能作为未见题迁移证据；每题每组一次也不用于估计重复可靠性。

## 默认合并库与此前实验

默认库已保留旧库并合入 K21–K40 共 20 张方法卡，现有 34 张父卡、79 条子记录，常规求解可用 63 条。`promote.py` 重新从已评分记录构建卡片，核对此前测试过的卡文、会话及交付指纹，然后更新默认审核语料、审核记录和索引。重复执行时不重复插卡；内容冲突则拒绝覆盖。

```sh
python3 -B benchmarks/experience-card-transfer/promote.py
```

合并后按当前项目 Skill 重跑原 20 题，只新增 Skill + 合并库的 20 个独立模型会话。题面及逐文件输入复制自原批次，强制一次经验检索并由模型判断采用。全部隔离预检完成后才启动模型；另行重算 8 道参考求解。以下命令真实发起模型调用及本地求解，批次目录必须尚不存在。

```sh
cohort=runs/merged-cards-20-repeat-03
python3 -B benchmarks/experience-card-transfer/rerun.py "$cohort" --workers 10 --timeout 1800
python3 -B benchmarks/three-arm-20/calibrate.py "$cohort"
python3 -B benchmarks/experience-card-transfer/rerun_score.py "$cohort" output/20题经验沉淀复跑
```

正式复跑批次为 `runs/merged-cards-20-20261119-02`。`-01` 在隔离预检发现单组运行没有 bare 对照工作区后停止，未发起模型请求；`-02` 改为探测另一道真实存在的题目工作区，继续验证跨题不可读。原题复跑单独报告，历史对照沿用旧批次；当前 Skill 有配置变化，因此不将历史用量差异表述为仅新增卡的因果效果。

[cards.tsv](cards.tsv) 保存 20 张候选卡的来源题号、标题、适用范围、检索词及操作。卡文及检索词均可在不读取历史答案的情况下复用。材料构建程序把核验通过的来源绑定到会话轨迹和交付文件，并使用项目原有的 BM25 引擎建立独立索引。出卡记录和本轮测试输入分别见 [materials.py](materials.py)。

本次批次位于 `runs/card-transfer-20261119-01`。其中 `new_cards/plugin/rag/experience/data/` 是 20 卡候选库，`card-audit.json` 保存来源，`manifest.json` 保存输入指纹与随机顺序，`scores.json` 是 24 次实测。以下命令仅查询这套候选库。

```sh
cards=runs/card-transfer-20261119-01/new_cards/plugin/rag/experience/data
python3 -B rag/experience/experience_rag.py query --query '氢析出份额 Css Cpp hydrogen precipitation' --corpus "$cards/reviewed_corpus.json" --index "$cards/experience_index.json" --limit 2 --compact
```

8 道迁移题使用独立的存档输入，覆盖 2 道真实求解、2 道原始场后处理与 4 道日志或观测表分析。题面、参数、数据与数值裁判在启动前固定。20 张卡全部对新卡组开放。旧卡与新卡组沿用相同的项目 Skill、角色与检索设置，仅经验语料和索引内容不同。对照组使用同版本 Skill，每道题有独立会话、输入副本和文件权限。

在已有批次上重新评分只读取后端数据。

```sh
python3 -B benchmarks/experience-card-transfer/score.py runs/card-transfer-20261119-01
```

复跑需使用新的批次目录，本机历史 20 题和 8 份测试材料需可读。下列第一步会真实发起 24 个模型会话，包含 6 次要求从初态执行 OFFBEAT 的任务。参考程序还会独立求解两次，并与保留的原结果交叉验证。

```sh
cohort=runs/card-transfer-repeat-02
python3 -B benchmarks/experience-card-transfer/trial.py "$cohort"
python3 -B benchmarks/experience-card-transfer/score.py "$cohort"
```
