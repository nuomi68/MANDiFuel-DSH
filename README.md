# MANDiFuel DSH · 燃料性能计算工作台

在浏览器中用中文描述工程问题，DSH 计算助手会准备 OFFBEAT 算例、运行求解器并提取结果。工作台随计算进度展示网格、物理场、曲线和表格。用户可以在同一会话里追问数值来源，或要求调整图表和标注。当前版本为 **0.4.0-alpha.8**。

## 启动 Web 工作台

**已有本机配置**时，从完整仓库的根目录启动工作台。

```bash
python3 frontend/server.py
```

打开终端打印的 **OFFBEAT 工作台**完整链接，首次登录需要链接中的一次性凭据。默认访问地址为 `http://127.0.0.1:18765/workbench/`。使用 VS Code Remote SSH 时，在「端口」面板转发 `18765` 后打开链接。端口已被占用时可用 `python3 frontend/server.py --port 18766`。在启动终端按 `Ctrl+C` 可停止服务。

### 首次配置

运行环境为 Linux 或 WSL，需 Bash、Python 3.12、Node.js 22 或更高版本，以及 DeepSeek DSH（已验证 0.1.2-rc.1）。计算端使用 OpenFOAM ESI v2506 和已编译的 OFFBEAT。验证所用的 OFFBEAT 提交为 `80e84450a115b0c411e1bfa5d166379f6bf6c084`。[DSH 安装说明](https://github.com/deepseek-ai/deepseek-harness) · [OFFBEAT 安装说明](https://foam-for-nuclear.gitlab.io/offbeat/installation.html)

1. 克隆完整仓库，进入项目目录并创建本机配置。

   ```bash
   git clone https://github.com/nuomi68/MANDiFuel-DSH.git
   cd MANDiFuel-DSH
   cp configs/launcher.env.example configs/launcher.env
   ```

2. 编辑 `configs/launcher.env`，填写 DSH、Node.js、Python 3.12、OpenFOAM 环境脚本和 OFFBEAT 可执行文件目录的绝对路径。`MANDIFUEL_CASE_LIBRARY_ROOT` 指向含 `Cases/` 的 OFFBEAT 源码根目录。模型和 API Key 在 DSH 中配置。使用外置数据盘的 `runs` 软链接时，把 `realpath runs` 的输出填入 `MANDIFUEL_RUNS_ROOT`。[配置模板](configs/launcher.env.example)
3. 检查计算环境，再启动工作台。需要运行绘图或优化示例时，在所配置的 Python 3.12 环境中执行 `python3.12 -m pip install -r requirements-examples.txt`。

   ```bash
   bash scripts/start-dsh.sh --check web
   python3 frontend/server.py
   ```

## 在网页里完成一次计算

1. 点击右上角 **＋（新建任务）**，在 **DSH** 对话窗输入算例、工况和想看的结果。可以复制仓库里的完整题面，例如让助手计算水冷通道升功率过程中壁温与冷却剂温度的变化。[水冷通道示例题面](examples/D1/prompt.txt)
2. 打开 **执行过程** 查看进度。工作台观察任务目录，有网格时可先预览模型，有保存场后可选择物理量和时刻。在已关联曲线与物理场的任务中，点击曲线上的数据点会切换到对应工况及最近的保存帧。
3. 继续在对话里提出显示要求，例如「把温度场改成蓝白红色带，标出当前帧最高温度的位置」。展示助手读取当前页面状态，按已有数据调整视图。打开 **结果核查** 可查看已支持工程量的来源文件、时刻、区域、单位、取数方法和核验状态。在 **交付文件** 中可查看本任务已登记的输入、日志和输出。

每个网页任务有独立工作区，默认位于 `runs/workbench/task-*/workspace/`。计算助手通过五项工程技能完成算例准备、求解、提取和研究任务。独立的展示助手观察文件变化、编排页面。相同的计算流程也可以在终端单独执行。任务子进程离线运行，文件写入边界覆盖项目目录和已登记的 `runs` 目录。[工作台使用说明与项目写入边界](frontend/README.md) · [展示助手角色与接口](frontend/agent/CONTRACT.md) · [独立数值核查](lib/mandifuel_verify/README.md)

## 工程示例与本地检索

仓库提供五份可直接粘贴到 DSH 对话窗的工程题面，包括水冷通道瞬态、TRISO 涂层厚度扫描、轴向功率形状优化、包壳氧化不确定性传播和铯扩散系数反演。[五个示例及计算条件](examples/README.md)

基准题库另收录 29 道题，包括 18 道新建模型求解题、1 道接续计算题和 10 道辅助题。点击题号可跳至完整题面，接续计算和已有结果分析题还需准备相应输入。[燃料性能基准题库](benchmark/题库总览.md)

选取参考模型时，助手可以联合查询 **137 张算例卡**和 **34 张经验父卡**。算例检索使用本地 BM25 和显式提供的九分面标签。经验库返回审核过的操作及其适用条件。1024 维描述向量供索引维护使用。运行中遇到输入错误时，助手会保留失败日志，在独立目录修复输入后重试，并按实际终点和保存场核对结果。[算例索引与来源](rag/PROVENANCE.md) · [经验检索](rag/experience/README.md) · [软件能力表](skills/prepare-offbeat-case/references/software-capabilities.md) · [输入恢复流程](skills/execute-offbeat-case/references/input-recovery.md)

## 终端运行与打包

批处理或后端评测可直接启动 headless 会话。以下命令从仓库根目录执行，将工作区放在项目的 `runs/` 下。

```bash
plugin_root="$PWD"
mkdir -p runs/manual
cd runs/manual
bash "$plugin_root/scripts/start-dsh.sh" headless '请说明当前算例准备需要哪些输入。'
```

在仓库根目录可校验随附题面和算例索引，或构建计算技能分发包。Web 工作台从完整仓库启动，以下打包命令面向后端技能。

```bash
python3 examples/run.py --check
python3 rag/build_index.py --check
python3 scripts/build-plugin.py --snapshot --output-dir /outside/source/releases
python3 scripts/package-source.py --output /outside/source/mandifuel-source.zip
```

Copyright (C) 2026 MANDiFuel contributors。项目采用 **GPL-3.0-or-later**，上游内容保留其权利。[许可证](LICENSE) · [项目声明](NOTICE) · [第三方声明](THIRD_PARTY_NOTICES.md)
