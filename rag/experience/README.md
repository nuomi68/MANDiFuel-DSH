# OFFBEAT 算例与审核经验检索

从项目根目录运行。Web 工作台和 headless 使用同一套检索入口，经验索引随插件分发。

```bash
python3 -I -B rag/experience/dual_query.py --query '球壳内压 hollow spherical shell pressure' --case-limit 5 --experience-limit 3 --compact
python3 -I -B rag/experience/experience_rag.py query --query '冷态直径与间隙 GapCold' --purpose solve --limit 3
python3 -I -B rag/experience/experience_rag.py query --query 'fuelRodGap gapGas 初始化失败' --purpose troubleshoot --arm skill --task-status incomplete --review-status troubleshooting_only
```

联合查询分别返回 `retrievers.case_rag` 和 `retrievers.experience_rag`，每侧有自己的 `status`、`output` 或错误信息。一侧出错时，整体状态为 `partial`，成功一侧的结果仍可读取。算例候选位于 `case_rag.output.candidates`，经验命中位于 `experience_rag.output.results`。英文工程关键词有助于检索算例卡。只需算例卡的调用者可继续使用 `rag/query.py`。

经验库采用本地 BM25，先按短条目检索，再返回父卡背景与相邻条目。每个命中包括 `score`、`child`、`parent_context` 和 `adjacent_children`。查询支持 `--query-file`，文本上限为 8,000 个字符。可用 `--source-run`、`--arm`、`--task-status` 和 `--review-status` 筛选经验来源，用 `--adjacent 0|1|2` 控制邻近范围。两个库的分数只在各自的候选列表内有意义。

## 审核范围

语料来自 2026-11-16 独立部署的 14 张父卡、59 条子记录。46 条审核通过，其中 3 条历史数值示例仅在显式指定 `--include-case-examples` 时可返回。其余 13 条限于排错。常规求解仅使用已完成计算或输入准备完成的通过项。`prepared` 表示输入准备完成。相邻条目也受来源与审核筛选约束。

逐条判定见 [审核记录](data/review_decisions.json)，审核文本、适用背景和来源组见 [经验语料](data/reviewed_corpus.json)。`source_question_server` 和 `source_session` 是相对于项目根的历史档案路径，查阅原始记录需要对应的 runs 档案。仅使用检索时，随包提供的语料和索引已经足够。经验的适用性仍需结合本次模型版本、输入、边界条件与结果核对。

## 更新索引与验证

```bash
python3 -I -B rag/experience/experience_rag.py build
python3 -m unittest discover -s benchmarks/experience-rag -p 'test_*.py'
python3 -I -B benchmarks/experience-rag/audit_invariants.py
python3 -I -B benchmarks/experience-rag/smoke_queries.py
```

语料校验和或引擎版本变化后重新构建索引。以上检索测试使用审核语料中的场景，不执行 OFFBEAT。
