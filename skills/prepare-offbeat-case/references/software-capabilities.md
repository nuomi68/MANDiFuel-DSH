# 当前安装的软件能力表

配置档 `local-offbeat-openfoam-v2506`；维护于 2026-11-14T14:57:54.756401+08:00。能力事实、接口和限制按来源分级，避免反复搜索或猜参数。

**先用关键事实**：关闭力学用当前已验证的mechanicsSolver constant；none不是通用关闭词。保留内部fuelRodGap导热时，核对它实际使用的气体物性。源功率和较晚时间末点已经满足请求就沿用。回读成功只证明写入，不能证明物理生效。

## 按本次改动定点查询

```bash
python3 "$MANDIFUEL_PLUGIN_ROOT/skills/prepare-offbeat-case/scripts/software_capabilities.py" show mechanicsSolver gapGas time
python3 "$MANDIFUEL_PLUGIN_ROOT/skills/prepare-offbeat-case/scripts/software_capabilities.py" check --case case --source source-case
```

一次查询可给多个选择器/主题；只读相关结果，不全表展开。check检查已知问题与直接依赖，错误与未核实项分开；无已知错误不等于整套物理已验证。新任务/未知值仍走一般准备、运行反馈与修复，默认不限次数。

| 内容 | 入口 |
|---|---|
| 13类模型选择器、合法关闭与旧名映射 | [模型](software-capabilities/models.md) |
| 温度/位移边界及耦合 | [边界](software-capabilities/boundaries.md) |
| 材料、本构、参数路径与几何 | [材料和几何](software-capabilities/materials-and-geometry.md) |
| 字段、单位、范围与坐标 | [字段单位](software-capabilities/fields-and-units.md) |
| 时间覆盖、写出、续算与完成 | [时间执行](software-capabilities/time-and-execution.md) |
| 公开工具和准确API签名 | [公共工具](software-capabilities/public-tools.md) |
| 意图组合、依赖与已知限制 | [操作和依赖](software-capabilities/dependencies-and-operations.md) |
| 供程序读取的统一事实源 | [catalog.json](software-capabilities/catalog.json) |

## 覆盖与证据

| 项 | 数量 |
|---|---|
| 本地检索卡片 | 137 |
| 有效源输入 | 136 |
| 排除的工具目录 | ['Cases/testCases/test_createTuFields'] |
| 正常执行记录（含重复组合） | 18 |
| 顶层选择器类别 | 13 |
| 已收录选择器值（证据分级） | 48 |
| 材料条目（含拼写未核实者） | 10 |
| 源卡确认拼写的材料选择器 | 8 |
| 材料物性/本构参数类别 | 20 |
| 源卡出现的物性/本构值 | 70 |
| 边界条目（按T/D/DD分别计） | 53 |
| 字段与单位条目 | 29 |
| 时间/求解控制条目 | 19 |
| 常用参数绑定 | 25 |
| 可组合任务意图 | 10 |
| 依赖/风险规则 | 13 |
| 结果公共API | 8 |

证据级别：runtime_verified=本机执行通过；registered=本机注册确认；documented=本地说明；input_observed=源卡出现；unverified=待核实。正常记录可重复同一模型，不构成全部组合验证。材料/属性/边界中的源卡观察不等于本机已执行认证。

136套带solverDict输入被纳入，另1个工具目录不含该字典。当前二进制SHA256为 `fd01aeacea13b98dc0fd346cf5ff55baa93df208a776d57531f1e9004c70b0f7`；共享库指纹记录在JSON。运行时沿用已准备环境，不逐题重复安装检查；软件升级由维护阶段更新本表。

本表为编译后的离线资料，不要求普通运行打开来源中的实现或维护证据；资料里出现的示例源路径仅供无源选型/维护追溯，已有source-case时不展开备用源。未列出不等于不支持。
