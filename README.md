# MANDiFuel DSH

面向OFFBEAT燃料性能分析的五项DSH技能，版本 **0.4.0-alpha.8**。

网页计算工作台入口为 `python3 frontend/server.py`。工作台保留原生 DSH
聊天与执行流程，通过独立前端 agent 编排交互图表、表格、参数和物理场；
计算 agent 按普通终端工作流运行。启动、项目写入边界与前端能力详见
[工作台说明](frontend/README.md)，前端角色和技能见
[接入契约](frontend/agent/CONTRACT.md)。

默认 Agent 身份是 **OFFBEAT 计算运行助手**：从输入卡、运行配方、公共接口和日志驱动现成软件，禁止查看或修改求解器、插件、生成器与解析器实现。错误恢复只处理本题输入和调用；无法依据本地使用契约解决时报告缺口。只有用户明确要求源码开发或分析时才按指定范围处理。任务目录内的改卡、调用和提取脚本属于运行批处理，不等于修改软件实现。

启动器替换 headless 的编码身份；Web 标准预设覆盖全局 persona 时，适配器在原生 prompt assembly 中同样替换最终身份段。长控制器或批量提取第一次即采用 DSH 原生后台任务，不假设前台超时会自动转后台。

## 计算完成与输入恢复

默认不限制真实 OFFBEAT 启动次数。用户要求完成计算时，依据运行反馈修复任务输入并重新求解属于正常流程；失败输入、日志和退出凭据保留，新尝试使用独立目录。成功结果复用，未见过的组合可以在通用输入流程中根据日志修正。只有用户明确设置的限制、停止请求或确认无法用允许输入与工具解决的阻塞才终止恢复。次数用于记账与成本统计，不能替代正确完成。详见[输入恢复闭环](skills/execute-offbeat-case/references/input-recovery.md)。

当前安装的选择器、合法关闭方式、材料与边界、参数路径、单位和公共接口，见[中文软件能力表](skills/prepare-offbeat-case/references/software-capabilities.md)。支持一次查询多个相关项；未收录项按一般准备和运行反馈继续，不作为禁止使用的白名单。

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
创建工作目录。普通任务只用本地资料与已安装软件，配置关闭网页工具和网页提供者；
所有受管任务子进程（含终端）通过 Linux seccomp 禁止远程网络套接字，后代进程继承。
原生文件沙箱、后台句柄、超时和进程清理仍由 DSH 管理；离线执行器不可用时拒绝启动。
DSH 宿主的模型 API 连接保留。支持 x86_64、aarch64 Linux，单机 OFFBEAT 计算无需外网。
本地 Unix 套接字与 netlink 保留用于进程和系统通信；跨主机 MPI 不属于离线执行路径。

无源算例时，RAG 默认从 `rag/` 附带的137张卡片进行本地词项与显式标签检索，
不需要检索 API Key，不生成在线查询向量。英文卡片应在同一次规划的查询中附英文工程关键词；
排序不代表物理适用性。旧的在线检索维护代码与缓存仅为索引维护留存，不进入任务路径。
headless模式使用启动命令所在的当前目录，例如：

```bash
plugin_root="$PWD"
mkdir -p "$HOME/mandifuel-runs/manual"
cd "$HOME/mandifuel-runs/manual"
bash "$plugin_root/scripts/start-dsh.sh" --check headless
bash "$plugin_root/scripts/start-dsh.sh" headless '请使用MANDiFuel技能完成当前工作区中的任务'
```

启动成功后，启动器向会话交接环境就绪状态、Python与OFFBEAT入口。普通计算直接准备输入卡、调用执行器并提取结果，不重复检查安装、动态库或求解器源码。输入参数、载荷覆盖、预算和真实终态仍须核对；实际报错才进入对应诊断。环境就绪状态只由成功的启动准备产生，不代表本题物理结果已经验证。

DSH 模型/API Key 由使用者在 DSH 中配置，不写入项目文件。任务子进程不再由适配器
转发 RAG 映射与嵌入密钥；普通任务也不得使用联网脚本补资料。

技能先于算例读取加载。已有 `source-case/` 时沿用该源，按变更一次读齐输入，
在一个脚本中完成独立目标、联动编辑、回读与运行准备，再一次提取请求量。
固定步长和物理续算见[本地配方](skills/execute-offbeat-case/references/time-and-restart.md)。

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
任务检索使用本地 BM25 与调用者显式标签；保留的向量索引供维护使用，默认任务不调用嵌入服务。来源和重建见
[RAG说明](rag/PROVENANCE.md)。

```bash
python3 rag/build_index.py --check
python3 scripts/build-plugin.py --snapshot --output-dir /outside/source/releases
python3 scripts/package-source.py --output /outside/source/mandifuel-source.zip
```

Copyright (C) 2026 MANDiFuel contributors。项目采用 **GPL-3.0-or-later**，
上游内容保留其权利，软件无担保。见[LICENSE](LICENSE)、[NOTICE](NOTICE)
和[第三方声明](THIRD_PARTY_NOTICES.md)。包中不含密钥、模型权重或单元测试。
