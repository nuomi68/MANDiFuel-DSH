# MANDiFuel DSH

本项目用于参加 **2026AIC·“AI+开源”算法主题赛赛题**。

MANDiFuel 是面向 OFFBEAT 燃料性能分析的 DeepSeek Harness（DSH）技能包，版本 **0.4.0-alpha.8**。五项技能覆盖研究任务编排、算例准备、数值求解、结果提取与参数研究，结合语义坐标系 RAG，从工程需求检索参考算例并驱动计算。

## 1. 依赖项

| 依赖 | 版本或用途 |
| --- | --- |
| Linux / WSL、Bash | 运行环境 |
| Python | 3.12 |
| Node.js | 22及以上 |
| DeepSeek DSH | 已验证0.1.2-rc.1，需自行配置模型/API Key |
| OpenFOAM | ESI v2506 |
| OFFBEAT | master快照，提交80e84450a115b0c411e1bfa5d166379f6bf6c084 |
| numpy、matplotlib、optuna | 示例计算、绘图与优化，见requirements-examples.txt |

各依赖自行安装。OFFBEAT以完整提交号标识版本，源码及安装方法见
[OFFBEAT官方说明](https://foam-for-nuclear.gitlab.io/offbeat/installation.html)。
[DSH官方仓库](https://github.com/deepseek-ai/deepseek-harness)提供安装和使用说明。
在所选Python 3.12环境中安装示例依赖：

```bash
python3.12 -m pip install -r requirements-examples.txt
```

## 2. 配置与启动

复制配置模板，手动填写DSH、Node.js、Python、OpenFOAM及OFFBEAT的绝对路径。
Python如使用虚拟环境，应填写该环境的入口路径。

```bash
cp configs/launcher.env.example configs/launcher.env
# 编辑 configs/launcher.env，替换路径占位符。
bash scripts/start-dsh.sh --check web
bash scripts/start-dsh.sh web
```

本机配置文件不进入分发包。`MANDIFUEL_CASE_LIBRARY_ROOT`填写含Cases目录的
OFFBEAT源码根目录。网页端的任务工作目录在DSH中选择，启动脚本不会切换或
创建工作目录。RAG默认使用插件安装目录下的`.cache/rag/`，不同任务共享查询缓存。
其中保存查询的语义坐标映射和查询向量，不保存求解结果；内置算例索引在`rag/index/`。
缓存按查询内容、模型配置和映射规则等区分，可删除后重建，也不进入Git或分发包。
如需指定其他缓存位置，可设置`MANDIFUEL_RAG_CACHE_DIR`为绝对路径。
从旧配置升级时，删除工作目录配置行及引用它的RAG缓存配置行。
headless模式使用启动命令所在的当前目录，例如：

```bash
plugin_root="$PWD"
mkdir -p "$HOME/mandifuel-runs/manual"
cd "$HOME/mandifuel-runs/manual"
bash "$plugin_root/scripts/start-dsh.sh" --check headless
bash "$plugin_root/scripts/start-dsh.sh" headless '请使用MANDiFuel技能完成当前工作区中的任务'
```

DSH模型/API Key由使用者在DSH中配置。五个示例的RAG模板检索均需在启动终端提供
`DEEPSEEK_API_KEY`和`DASHSCOPE_API_KEY`；不要把真实密钥写入项目文件。
DSH模型设置与RAG接口设置分别生效，嵌入模型须与索引保持一致。

## 3. 五个示例

```bash
python3 examples/run.py --check
python3 examples/run.py D1 --workspace "$HOME/mandifuel-runs/D1"
```

将D1替换为D2、D3、D4或D5即可运行其他示例。D1为水冷通道瞬态，
D2为TRISO厚度扫描，D3为轴向功率形状优化，D4为氧化不确定性传播，
D5为铯扩散系数反演。五个示例均从工程需求开始，由准备技能通过RAG
选择参考算例并准备输入，随后开展OFFBEAT计算。详见[示例说明](examples/README.md)。

## 4. RAG、构建与许可

内置137张卡片、9个语义分面和1024维向量，索引模型为text-embedding-v3。
检索采用0.65标签坐标得分与0.35向量得分融合。来源和重建见
[RAG说明](rag/PROVENANCE.md)。

```bash
python3 rag/build_index.py --check
python3 scripts/build-plugin.py --snapshot --output-dir /outside/source/releases
python3 scripts/package-source.py --output /outside/source/mandifuel-source.zip
```

Copyright (C) 2026 MANDiFuel contributors。项目采用 **GPL-3.0-or-later**，
上游内容保留其权利，软件无担保。见[LICENSE](LICENSE)、[NOTICE](NOTICE)
和[第三方声明](THIRD_PARTY_NOTICES.md)。包中不含密钥、模型权重或单元测试。
