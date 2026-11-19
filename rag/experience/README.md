# OFFBEAT 算例与审核经验检索

从项目根目录运行。Web 工作台和 headless 使用同一套检索入口，经验索引随插件分发。

```bash
python3 -I -B rag/experience/dual_query.py --query '球壳内外恒压 hollow spherical shell internal external pressure' --labels-json '{"geometry":["1D_spherical"],"driving_condition":["constant_pressure"]}' --case-limit 5 --experience-limit 3 --compact
python3 -I -B rag/experience/experience_rag.py query --query '冷态直径与间隙 GapCold' --purpose solve --limit 3
python3 -I -B rag/experience/experience_rag.py query --query 'fuelRodGap gapGas 初始化失败' --purpose troubleshoot --arm skill --task-status incomplete --review-status troubleshooting_only
```

联合查询分别返回 `retrievers.case_rag` 和 `retrievers.experience_rag`，每侧有自己的 `status`、`output` 或错误信息。一侧出错时，整体状态为 `partial`，成功一侧的结果仍可读取。算例候选位于 `case_rag.output.candidates`，经验命中位于 `experience_rag.output.results`。英文工程关键词有助于检索算例卡。只需算例卡的调用者可继续使用 `rag/query.py`。

无指定源的计算任务由主助手按 `rag/index/vocabulary.json` 选取题目支持的标签，在同一次联合查询里传入。要检查分面是否实际参与，查看算例侧的 `query_mapping.mapped_labels`、`fusion.weights` 和候选的 `matched_labels`、`score_components`。有标签时按归一化 BM25 的 60% 和分面得分的 40% 排序，显式命中完整算例路径另计加分。未传标签时分面权重为零。任务检索离线运行，描述向量不参与此处打分。经验卡使用独立的 BM25 排序。

经验库采用本地 BM25，先按短条目检索，再返回父卡背景与相邻条目。每个命中包括 `score`、`child`、`parent_context` 和 `adjacent_children`。查询支持 `--query-file`，文本上限为 8,000 个字符。可用 `--source-run`、`--arm`、`--task-status` 和 `--review-status` 筛选经验来源，用 `--adjacent 0|1|2` 控制邻近范围。两个库的分数只在各自的候选列表内有意义。

## 审核范围

默认语料在 2026-11-19 合入原 20 题提炼的 K21–K40 方法卡，保留 2026-11-16 旧库全部内容及审核边界。现有 34 张父卡、79 条子记录。66 条审核通过，其中 3 条历史数值示例仅在显式指定 `--include-case-examples` 时可返回；常规求解可用 63 条。其余 13 条限于排错。常规求解仅使用已完成计算或输入准备完成的通过项。`prepared` 表示输入准备完成。相邻条目也受来源与审核筛选约束。

新增卡的来源题号、核验会话、交付文件及 SHA-256 见 [20 卡审核来源](data/card_transfer_review.json)。卡片只包含有适用条件的方法，不录入来源题的答案数值。合并前已经过 8 道新题的独立迁移实测；合并后的原 20 题复跑属于原题回归，不能当作新题迁移收益。出卡与复跑入口见 [归档版经验卡实验](https://github.com/nuomi68/MANDiFuel-DSH/blob/1bf63584c535270572338a17414569dc99db1195/benchmarks/experience-card-transfer/README.md)。

逐条判定见 [审核记录](data/review_decisions.json)，审核文本、适用背景和来源组见 [经验语料](data/reviewed_corpus.json)。`source_question_server` 和 `source_session` 是相对于项目根的历史档案路径，查阅原始记录需要对应的 runs 档案。仅使用检索时，随包提供的语料和索引已经足够。经验的适用性仍需结合本次模型版本、输入、边界条件与结果核对。

## 更新索引与验证

```bash
python3 -I -B rag/experience/experience_rag.py build
python3 -m unittest discover -s tests/experience-rag -p 'test_*.py'
python3 -I -B tests/experience-rag/audit_invariants.py
python3 -I -B tests/experience-rag/smoke_queries.py
```

语料校验和或引擎版本变化后重新构建索引。以上检索测试使用审核语料中的场景，不执行 OFFBEAT。
