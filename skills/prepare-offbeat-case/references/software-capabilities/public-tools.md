# 软件能力表：当前本地 OFFBEAT

仅为声明安装的已知能力索引。执行通过不证明所有组合/精度；未列出不等于不支持。运行助手查询本表，不读取维护源码。

维护时间：2026-11-14T14:57:54.756401+08:00。配置档：`local-offbeat-openfoam-v2506`。

安装身份由维护阶段记录；运行助手沿用启动器已准备环境，不为查询本表重复检查安装或源码。升级软件/加载新扩展后应由维护者更新配置档，不能把旧注册事实强套到新安装。

证据级别：runtime_verified=本机执行通过；registered=本机注册确认；documented=本地说明；input_observed=源卡出现；unverified=待核实。源卡出现仅证明语法被写过；本机执行通过仅覆盖记录中的组合。

## 公共工具入口

| 入口 | 能力 |
|---|---|
| foam_edit | get_foam_entry / set_foam_entry，已有项的原生编辑与回读；不会检查全部物理语义。 |
| case_runner | run_case / inspect_case，保存执行状态、实际终点和diagnostic；同目录幂等，修复后新尝试。 |
| parameter_plan | 已验证Cs常D范围内的批量准备/执行/实际场核对，不作为全部任务入口。 |
| Study | 多评价历史与调度，prepare/execute/evaluate/collect，按实际公开说明使用；默认不限制求解次数。 |
| generators | rodDict/rod3Ddict.json/sphereDict是输入；调用配方中的现成生成器，不读实现。 |
| postProcess | 纯后处理，可生成C/V；不因提取错误重算物理过程。 |

## 提取API：实际导出签名

以下签名由当前public result_api.py的AST核对。运行任务按此调用，不需要查看实现。list_scopes确实存在；有空defaultFaces时范围查询会报解析错误，不代表函数不存在。

```python
list_times(result_root: str | Path, variable: str | None=None, *, source: str='fields')
```
列出求解或后处理的数值时刻，可限定必须含有某个场。

```python
list_variables(result_root: str | Path, *, time: TimeSelector='latest')
```
描述一个时刻或全部求解时刻中可读的体场。

```python
list_scopes(result_root: str | Path, *, time: TimeSelector='latest')
```
返回解析时刻网格中的具名单元区与边界。

```python
describe_field(result_root: str | Path, variable: str, *, time: TimeSelector='latest')
```
返回字段绑定；dimensions使用精确、可序列化的十进制字符串。

```python
describe_mesh(result_root: str | Path, *, time: TimeSelector='latest')
```
返回相对于结果根目录的、与所选时刻绑定的网格文件路径。

```python
iter_fields(result_root: str | Path, variable: str, *, time: TimeSelector='latest', scope: Scope='internal', component: str='value', location: Location | None=None, owner_zone: str | None=None, entry_name: str='value', include_volumes: bool=False)
```
逐时刻迭代选定帧，支持相应的动网格几何。

```python
read_field(result_root: str | Path, variable: str, *, time: TimeSelector='latest', scope: Scope='internal', component: str='value', location: Location | None=None, owner_zone: str | None=None, entry_name: str='value', include_volumes: bool=False)
```
读取标量分量或principal_max；time=all将全部帧载入内存。

```python
extreme(result_root: str | Path, variable: str, *, operation: Literal['max', 'min', 'max_abs']='max', details: bool=False, **selection: object)
```
对一个或全部时刻的选定场求极值；默认返回float。

## 使用和限制

component：标量value；向量x/y/z；对称张量xx/xy/xz/yy/yz/zz或principal_max。没有mag；需要幅值时在同一选择上组合分量。sigmaCyl的radial/hoop/axial便利分量按其坐标约定使用。

read_field(time="all")会物化全部帧；iter_fields可逐帧消费。同一次历史读取中，未变化的网格几何只重建一次；缓存按真实网格来源和文件版本区分，移动网格或文件变化仍使用对应几何，且不跨调用保留。同一场的统计与表复用已读结果，长提取从首次提交就使用原生后台句柄。当前大网格/重复几何解析可能耗时，不重复前台测时直到超时。

面场不由list_variables完整列出。仅需原始均匀/列表边界条目时可用foamDictionary读取dimensions和boundaryField/<patch>/value，避免重建网格。需要面积/坐标/标签时仍要有相应几何证据。

0面defaultFaces可能触发list_scopes解析异常；原生网格有效，不删面、不改物理、不重算。已知材料区可继续尝试已说明的字段选择，或使用原生后处理与明确的实际范围；不私自重写底层解析器。

几何字面量裸列表与新增未支持语法可用任务局部输入代码；已有字典替换复用foam_edit。原生回读验证写入，软件模型组合由已知检查和真实结果另行核对。
