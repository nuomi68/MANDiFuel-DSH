# 生成器管理的燃料棒和颗粒尺寸

只修改生成器的参数输入文件，调用现成生成器，不查看或修改 `rodMaker.py` 等实现源码。执行配方会调用生成器时，参数修改和回读完成相应准备，字典及网格由配方产生。只有用户要求交付字典时，才在目标运行生成器并把输出放到 `system/blockMeshDict`。派生顶点及网格表示由生成器负责。

| 绑定 | 解释 |
|---|---|
| `rodDict` → `rodMaker.py`，一维或二维r-z棒 | `rInnerFuel`、`rOuterFuel` 及包壳对应项是块半径；高度和偏移定义轴向几何，长度通过 `convertToMeters` 换算；输出位于工作目录 |
| `rod3Ddict.json` → `rod3Dmaker.py` | `fuelInnerRadius`、`fuelOuterRadius`、`cladInnerRadius`、`cladOuterRadius`、`rodHeight`、`center`、`unit` 定义几何；原生版本只读数组首项并写字典 |
| `sphereDict` → 源的 `sphereMaker.py` 或 `octantSphereMaker.py` | `rKernel` 是半径，`tBuffer`、`tIPyC`、`tSiC`、`tOPyC` 是厚度；常见启用层约定中间隙位于Buffer之后：IPyC内半径为 `rKernel+tBuffer+gap`，外半径再加 `tIPyC` |

派生尺寸序列化时保留足够有效数字，顶点坐标由生成器换算。在相同轴向位置，径向间隙为包壳内半径减燃料外半径，壁厚为包壳外半径减内半径；增大燃料半径且保持两者不变时，两个包壳半径一起平移。

若燃料材料中已有 `DiamCold`、`GapCold`，它们分别是米制燃料外直径和直径间隙：`DiamCold=2*rOuterFuel`，`GapCold=2*(rInnerClad-rOuterFuel)`，先转换单位。改变对应几何时同步这些已有项。不能仅因数值相同就联动独立端盖半径或固定空间探针。

上述球形层约定中，`gap` 增加 `dg` 会使IPyC、SiC、OPyC的所有半径增加 `dg`，Kernel与Buffer不变。IPyC-SiC界面探针半径为 `rKernel+tBuffer+gap+tIPyC`，再换算为米。标准OFFBEAT `trisoGap` 的 `jumpDistance` 是热跳跃贡献，不是几何间隙宽度；只改几何时保留该输入。
