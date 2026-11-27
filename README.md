# MANDiFuel DSH · 燃料性能计算工作台

MANDiFuel DSH 是基于 DeepSeek Harness 和 OFFBEAT 的核燃料性能计算工作台。用中文描述工程问题，计算助手会选择参考算例、准备并回读输入、运行求解器，在独立工作区保存结果和执行回执。可以在浏览器里与它协作，也可以在终端独立运行相同的计算流程。

例如，研究燃料棒稳态传热时，可以先查看径向温度曲线，再要求标出燃料区最高温度，点开核查记录查看热源积分和外壁散热的单位、取值区域与来源文件。展示助手根据已有保存场和当前页面调整图表、表格与物理场。对于支持的燃料棒模型，还可以开启 **生成计算器**，把一次成功的计算保存为可复算的应用，以后修改线功率或外壁温度即可运行新工况。[基准题库](benchmark/题库总览.md) · [独立数值核查](lib/mandifuel_verify/README.md) · [计算器支持范围](lib/mandifuel_app/CONTRACT.md)

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

2. 编辑 `configs/launcher.env`，填写 DSH、Node.js、Python 3.12、OpenFOAM 环境脚本和 OFFBEAT 可执行文件目录的绝对路径。`MANDIFUEL_CASE_LIBRARY_ROOT` 指向含 `Cases/` 的 OFFBEAT 源码根目录。DSH 对话模型按宿主配置。默认语义选源还需在启动进程环境中设置 `DEEPSEEK_API_KEY` 和 `DASHSCOPE_API_KEY`，也可在模板中指定其他凭据变量名。使用外置数据盘的 `runs` 软链接时，把 `realpath runs` 的输出填入 `MANDIFUEL_RUNS_ROOT`。[配置模板](configs/launcher.env.example)
3. 检查计算环境，再启动工作台。需要绘图或运行参数优化时，在所配置的 Python 3.12 环境中执行 `python3.12 -m pip install -r requirements-examples.txt`。

   ```bash
   bash scripts/start-dsh.sh --check web
   python3 frontend/server.py
   ```

## 在网页里完成一次计算

1. 点击右上角 **＋（新建任务）**，在 **DSH** 对话窗输入算例、工况和想看的结果。首次使用可以复制题库中的 C01，让助手计算燃料棒的稳态温度分布，并核对燃料产热与包壳向外散热。[C01 完整题面](benchmark/题库总览.md#c01-燃料棒稳态传热建模与总热流)
2. 打开 **执行过程** 查看进度。工作台观察任务目录，有网格时可先预览模型，有保存场后可选择物理量和时刻。在已关联曲线与物理场的任务中，点击曲线上的数据点会切换到对应工况及最近的保存帧。
3. 继续在对话里提出显示要求，例如「把温度场改成蓝白红色带，标出当前帧最高温度的位置」。展示助手读取当前页面状态，按已有数据调整视图。打开 **结果核查** 可查看已支持工程量的来源文件、时刻、区域、单位、取数方法和核验状态。在 **交付文件** 中可查看本任务已登记的输入、日志和输出。

每个网页任务的工作区默认位于 `runs/workbench/task-*/workspace/`。求解子进程离线运行，可写范围为项目目录和已登记的 `runs` 目录。展示助手观察文件变化，根据计算进度和用户的后续要求编排页面。[工作台使用说明](frontend/README.md) · [展示助手角色与接口](frontend/agent/CONTRACT.md)

## 让 DSH 生成可复算的科学应用

新任务右上角、**DSH** 左侧的 **生成计算器** 开关默认关闭。可在发送任务前开启，也可在计算过程中开启或取消。工作台按任务保存选择，成功计算有可用工况后才启动专用构建会话。已有结果时，也可在 **构建要求** 中指定参数或输出。生成期间可关闭开关取消。原始结果始终可以查看。

标题下显示当前计算和渲染状态。点击 **执行过程**，可按发生时间查看科学计算、UI 操作与浏览器回执。

点击 **打开计算器** 可查看参数和单位。输入与已保存工况相同时，**查看已有结果** 直接载入该工况。改为一组新值，再点击 **重新计算**，运行层会回读新输入并启动 OFFBEAT，无需再次调用大模型。工况下拉框可以切回原始结果。继续在右侧对话中描述新需求可修改同一个应用。

普通复算直接复制归档输入，回读修改后的物理绑定，在独立工况目录执行 OFFBEAT。当前注册了恒物性、恒线功率、固定包壳外壁温度的单轴向截面燃料棒输入族。应用定义及各版本在任务目录的 `applications/<appId>/` 下，执行回执与原始温度场按运行归档。终端可以独立创建、修改和执行同一契约。[契约与终端使用说明](lib/mandifuel_app/CONTRACT.md)

## 基准题库与算例检索

基准题库收录 29 道题，包括 18 道新建模型求解题、1 道接续计算题和 10 道辅助题。点击题号可跳至完整题面，接续计算和已有结果分析题还需准备相应输入。[燃料性能基准题库](benchmark/题库总览.md)

选取参考模型时，助手可以联合查询 **137 张算例卡**和 **34 张经验父卡**。Web 和终端的计算助手通过 `mandifuel_retrieve` 选源。默认由 DeepSeek 将选源短句映射为九分面标签并生成英文检索改写，DashScope 将改写编码为 1024 维向量。本地使用描述相似度（35%）与置信度加权的分面匹配（65%）排序；经验库独立返回审核过的操作及其适用条件。设置 `MANDIFUEL_RAG_MODE=local` 可使用离线 BM25 与显式标签。运行中遇到输入错误时，助手会保留失败日志，在独立目录修复输入后重试，并按实际终点和保存场核对结果。[算例索引与来源](rag/PROVENANCE.md) · [经验检索](rag/experience/README.md) · [软件能力表](skills/prepare-offbeat-case/references/software-capabilities.md) · [输入恢复流程](skills/execute-offbeat-case/references/input-recovery.md)

## 终端运行与打包

批处理或后端评测可直接启动 headless 会话。以下命令从仓库根目录执行，将工作区放在项目的 `runs/` 下。

```bash
plugin_root="$PWD"
mkdir -p runs/manual
cd runs/manual
bash "$plugin_root/scripts/start-dsh.sh" headless '请说明当前算例准备需要哪些输入。'
```

在仓库根目录可校验算例索引，或构建计算技能分发包。Web 工作台从完整仓库启动，以下打包命令面向后端技能。

```bash
python3 rag/build_index.py --check
python3 scripts/build-plugin.py --snapshot --output-dir /outside/source/releases
python3 scripts/package-source.py --output /outside/source/mandifuel-source.zip
```

Copyright (C) 2026 MANDiFuel contributors。项目采用 **GPL-3.0-or-later**，上游内容保留其权利。[许可证](LICENSE) · [项目声明](NOTICE) · [第三方声明](THIRD_PARTY_NOTICES.md)
