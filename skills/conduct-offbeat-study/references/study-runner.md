# Study 公共接口

## 导入与组件绑定

使用当前插件根目录导入薄入口，避免复制库实现：

```python
import os
import sys
from pathlib import Path

PLUGIN = Path(os.environ['MANDIFUEL_PLUGIN_ROOT'])
sys.path.insert(0, str(PLUGIN / 'skills/conduct-offbeat-study/scripts'))
from study_runner import Study
ROOT = Path(__file__).resolve().parent
```

```python
study = Study(ROOT, prepare=prepare, command=['bash', 'run.sh'],
              progress=extract_progress)
```

`prepare(point)` 返回独立算例路径，执行配方包含预处理并在算例目录运行；`extract_progress(result_root)` 返回算法需要的标量或小型映射。固定点表可省略 `progress`，求解后再集中收集。`log`、`end_time`、`timeout` 调整执行器设置；定制 `execute(case)` 返回终态 `status`、绝对 `result_root` 和完成证据。

```python
study = Study(ROOT, prepare=prepare, command=['bash', 'run.sh'])
history = study.run(points, workers=workers)
history = study.collect(extract_reporting)
```

`run` 返回按提议顺序保存的累计历史，不是单个记录。优化目标回调中的新点可使用 `study.run([point], workers=1)[-1]`。记录的 `response` 是推进响应，`final_time`、`result_root` 等是旁边的执行元数据。

## 固定扫描定义文件

将 Orchestrate 的 `assets/fixed_study.py` 复制为工作区的 `study.py`，同目录提供 `study_definition.py`。定义文件只负责点、物理输入与响应，调度和去重由共享库实现。

以下示例假设 Prepare 已在当前工作区选好 `reference-case/`，其中有已确认的三节点LHGR历史、`fuel`材料区、可用 `run.sh`，且时间与模型设置已满足本题。具体参数、字段和区域按请求替换：

```python
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent
PLUGIN = Path(os.environ['MANDIFUEL_PLUGIN_ROOT'])
sys.path.insert(0, str(PLUGIN / 'skills/prepare-offbeat-case/scripts'))
sys.path.insert(0, str(PLUGIN / 'skills/extract-offbeat-results/scripts'))
from foam_edit import get_foam_entry, set_foam_entry
import result_api

SOURCE = ROOT / 'reference-case'
POINTS = [
    {'id': 'p01', 'lhgr_values': '(0 18000 18000)'},
    {'id': 'p02', 'lhgr_values': '(0 22000 22000)'},
]
WORKERS = 1
COMMAND = ['bash', 'run.sh']

def prepare(point):
    target = ROOT / 'cases' / point['id']
    shutil.copytree(SOURCE, target)
    readback = set_foam_entry(target, file='constant/solverDict',
                              entry='heatSourceOptions/lhgr',
                              value=point['lhgr_values'])
    (target / 'prepare.json').write_text(json.dumps(readback, ensure_ascii=False))
    return target

def extract_reporting(result_root):
    final_time = get_foam_entry(result_root, 'system/controlDict', 'endTime')
    return {'fuel_T_max_K': result_api.extreme(
        result_root, 'T', operation='max', time=final_time,
        scope=('cellZone', 'fuel'))}

def write_report(history):
    table = [{'point': r['point'], 'status': r['status'],
              'response': r.get('reporting_response')} for r in history]
    (ROOT / 'results.json').write_text(json.dumps(table, ensure_ascii=False, indent=2))
```

已有目标目录不应无条件删除。示例用 `copytree` 在路径冲突时明确失败，Study重复执行会跳过已记录身份；准备失败后的修复或授权重试使用明确的独立身份与路径。只有任务绑定需要改变，不复制模板的调度循环。

模板接受 `POINTS`、`prepare`、`extract_reporting`，可选 `WORKERS`、`COMMAND`、`write_report`。默认串行和 `['bash', 'run.sh']`。`study-summary.json` 分别记录求解与提取完成数；任一请求点缺失、失败或收集失败时返回非零。报告回调可以交付明确标记的部分结果，不会将失败改记为成功。

## 接入已有评价器

完整 `evaluate(point)` 已负责准备、执行及推进提取时，用 `Study(ROOT, evaluate=evaluate)`，不再同时提供 `prepare`。返回可JSON序列化的终态记录；正常成功必须有绝对 `result_root`，算法需要时提供 `response`。

非空 `response` 默认标记 `progress_status='completed'`；若正常求解后提取失败，保留 `status='completed'`，设置 `progress_status='failed'`、`response=None` 与 `progress_error`。未捕获评价异常记录为 `evaluation_failed`。可选 `progress(result_root)` 能补充缺失推进响应或修复提取，已完成的响应复用。

## 点、调度与预算

点是JSON字典，例如 `{'id':'p01','x':0.5}`，整个字典构成身份。授权重试或随机复测使用不同身份和目标目录；已有记录不会自动再评价。

`max_evaluations` 是累计历史条目上限，包含接纳的点和准备失败，绝不是物理求解启动计数。任务预算按实际OFFBEAT启动统计，包括失败；求解前的准备失败不消耗物理启动。恢复时依据保留启动证据核算，不以 `len(history)` 或优化试验数替代。

```python
history = study.run(next_points=next_points, workers=workers,
                    max_evaluations=attempt_limit)
```

`next_points(history)` 接收终态历史，返回当前就绪点列表，返回空列表表示结束。Study在worker和历史上限内调度未见身份。固定表会继续调度其中未记录的点并保存失败，不自动重试；需要按故障决定是否继续时，在方法的提议逻辑中明确处理。同步种群在当前代所有必要记录齐全后再更新并提供下一代；顺序自适应使用一个worker。

## 记录、收集和恢复

记录包含 `point`、求解 `status`、可用的 `result_root`、推进 `response`；公共执行器还返回 `end_time`、`final_time`、`times`、`exit_code`、`solver_seconds`、`solver_steps`、`wall_seconds`、`terminal_marker` 和日志路径。`completed` 已结合正常结束与终点数值相等判断，不必再按目录字符串拼写判断。

`Study.collect(extract_reporting)` 只读取正常完成的根，保存 `reporting_response`、`reporting_status`，复用已经成功的收集；失败收集可修复后继续。它不会自动检测“回调改了选择”：新增响应要作为明确的新提取步骤保存，不把旧成功映射当作新值。优化惩罚属于方法记录，不是不可用物理量的替代值。

同根重新构造Study会加载 `history.json`，仅调度未见身份。修复 `progress` 后可恢复成功求解的缺失提取；中断点显式保留。只有协调器写历史。

`study.adopt(point, completion, response=value)` 接纳已有正常完成及响应，不准备、不运行、不提取；历史已有该点时通常不需要再次接纳。外部求解先用 Execute 的 `inspect_case` 获取证据。非零退出的场不能接纳为正常完成，修复读者错误也不能改写真实失败。

预计较长的控制器或批量提取，第一次就通过 Bash 的 `run_in_background: true` 提交，随后用原生作业句柄等待终态。短命令可前台执行并设合理超时。前台超时会终止进程，不会自动变成后台作业；不能因等待返回中间状态而重复启动。控制器结束才代表其所含阶段结束。
