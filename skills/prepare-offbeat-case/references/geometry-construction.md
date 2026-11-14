# 构建新的燃料棒几何

现有结构不能表达请求时，在独立目标目录中使用适合的模板或生成器构建替代几何。

| 目标 | 输入与构建方式 |
|---|---|
| 一维径向燃料棒 | `rodDict` 中 `geometryType: '1D'`，由 `rodMaker.py` 读取 |
| 二维r-z连续燃料柱 | `geometryType: '2Dsmeared'`；块名、半径、高度、偏移和单元数描述轴向分段 |
| 二维r-z离散芯块 | `geometryType: '2Ddiscrete'`；`nPelletsFuel` 划分燃料块，按源生成器支持的凹坑、倒角参数设置 |
| 二维r-theta横截面 | 横截面模板的显式 `blockMeshDict` 或导入网格；`rodMaker.py` 是r-z生成器 |
| 完整周向三维燃料/包壳棒 | `rod3Ddict.json` 由 `rod3Dmaker.py` 读取；原生版本仅构建固定燃料/包壳区域的一个轴向段，数组取首项，不是通用装配器，也没有通用纯包壳开关 |
| 纯包壳试样 | 使用已有环形块网格的纯包壳模板，例如伪PUZRY算例，其区域和边界已经代表该试样 |

在目标目录中运行生成器和参数文件。原生 `rodMaker.py`、`rod3Dmaker.py` 在工作目录写出 `blockMeshDict`；需要字典交付时移动到 `system/blockMeshDict`。

执行配方中的 `blockMesh` 根据字典生成网格。材料分配和场边界名称必须匹配生成的 cellZone 和 patch。共享界面使用共享连接；接触面可能要求各自独立、成对的 patch。坐标缩放不能创建不存在的界面。
