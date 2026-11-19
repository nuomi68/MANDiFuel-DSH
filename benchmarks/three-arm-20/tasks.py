"""Frozen engineering requests, quantities and data provenance for the paired evaluation."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
RUNS=ROOT/'runs'
def wb(task,path):
    return f'workbench/task-{task}/workspace/{path}'

sources={
    'heat':wb('8b11770530044ecc','case'), 'shell':wb('74e7e689d9204f6f','case2'),
    'adiabatic':wb('f2cec6a460014780','case'), 'bareCs':wb('3e144f0337f84309','case'),
    'cylinder':wb('d53b066f8e394536','cases/p10'),
    'creep':'capability-pairs-20261114-01/C05/skill/workspace/case',
    'oxide':'run-assistant-c04-20261113-01/C04/skill/workspace/case',
    'gas':'threeway-experience-20261116-gap-01/D_new_GapVolume/skill/workspace/case',
    'triso':wb('91265ed0b03640cb','cases/S3-full-coating'),
    'rod':'token-pairs-20261117-01/T02/skill/workspace/case',
    'ring':wb('be526840bf774a27','cases/p01_rhole_0.50mm'),
    'hydrogen':'threeway-experience-20261116-03/C_new_Hydrogen/skill_rag/workspace/case-h2-ingress-1000d-attempt03/postProcessing/average/0/volFieldValue.dat',
    'modulus':wb('94ab971aa2e04bd7','results/inversion-table.csv'),
    'conductance':wb('0c17d02a665b4726','results.csv'),
    'power':'token-pairs-20261117-01/T03/skill/workspace/params-status-response.csv',
    'size':wb('be526840bf774a27','results/summary.csv'),
}
# Each item has two independently scored numeric quantities, ordered as in the prompt.
# Input visibility: solver cases get initial dictionaries only, field tasks get only
# named raw frames/mesh, table tasks get only observation columns.
TASKS=[
 ('S01','稳态导热与燃料峰值','heat','solve','按现有外壁恒温载荷完成稳态导热，报告终态燃料区单元最高温度及全网格积分体积热源功率（当前模型，不扩展到整棒）。',['K','W']),
 ('S02','受压球壳双表面位移','shell','solve','完成内外受压球壳小应变求解，给出终态内、外表面沿向外半径方向的平均位移，有符号，取保存边界场。',['µm','µm']),
 ('S03','绝热瞬态储能温升','adiabatic','solve','保持绝热边界完成瞬态热计算。求在 10 s 时 fuel 单元最高温度，及 fuel 体积平均温度从首个非零保存时刻到 10 s 的增量。',['K','K']),
 ('S04','裸球核铯库存与外释','bareCs','solve','计算至 50000 s，给出终态单元最高铯浓度、按初始均匀 1 mol/m³ 和真实网格体积积分得到的累计释放分数。',['mol/m³','1']),
 ('S05','双材料圆筒径向变形','cylinder','solve','求解双材料圆筒压力工况，分别给出 inner、outer 两个材料区的单元最大径向位移，采用以 z 为轴的柱坐标分量。',['µm','µm']),
 ('S06','SiC 辐照蠕变','creep','solve','保持给定辐照和载荷运行至 2e8 s。给出末帧全模型单元最大累计等效蠕变应变、最大等效应力。',['1','MPa']),
 ('S07','长期包壳氧化','oxide','solve','保持现有温度和腐蚀模型运行到输入指定终点，求 cladOuter 最后两个保存帧氧化层厚度的面平均值，按先后顺序。',['µm','µm']),
 ('S08','扇区气隙与贮气腔','gas','solve','完成气隙气体体积模型求解，给出终态模型扇区的气隙体积，以及对应 360° 整棒的上下贮气腔体积之和。',['m³','m³']),
 ('P09','TRISO 指定区域的点测量','triso','field','读取 432000 s 已保存 Cs 场。在 Kernel 区取单元中心离半径 230 µm 最近的值，并求同一时刻 Buffer 区体积加权平均浓度。径向位置以球心为原点。',['mol/m³','mol/m³']),
 ('P10','燃料棒材料分区平均','rod','field','分别计算终态 fuel、cladding 区的体积加权平均温度，按有限体积和真实 cellZone 统计。',['K','K']),
 ('P11','球壳应力张量投影','shell','field','从末帧应力张量取离球心最近的单元，给出径向正应力和两个切向正应力的平均，拉为正。',['MPa','MPa']),
 ('P12','界面两侧压差响应','cylinder','field','从末帧保存场求 inner 材料和 outer 材料中最大的 von Mises 应力，分别统计，不包括边界面。',['MPa','MPa']),
 ('P13','环形燃料外表面与内部峰值','ring','field','读末帧，各给出环形燃料外表面面积加权平均温度和 fuel 区单元最高温度，区分面值与单元值。',['K','K']),
 ('P14','快中子注量累积','creep','field','从两帧 fastFluence 场求各自全模型单元最高值的差（后减前）及增量除以物理秒数得到的平均快通量。',['n/m²','n/(m²·s)']),
 ('P15','氢的固溶与析出分解','hydrogen','table','这份不完整运行的原生体积平均日志有多次采样。取最后一个三项氢浓度齐全的采样，给出固溶氢浓度，以及析出氢占两相浓度和的比例。',['wt.ppm','1']),
 ('P16','瞬态扩散的半量释放时刻','bareCs','field','用所给各保存帧的全核体积积分求释放分数，初始浓度均匀 1 mol/m³。给出首次跨过 0.5 时的线性插值时刻和最后保存帧的释放分数。',['s','1']),
 ('D17','内层模量的反演与灵敏度','modulus','table','只用所给已计算观测，找界面位移 2.05 µm 两侧最近的样点，分段线性插值得到内层模量，并求这段的位移对模量斜率。',['GPa','µm/GPa']),
 ('D18','热隙不确定性样本的分位数','conductance','table','将四个热隙换热样本等权，统计燃料峰温的总体标准差（分母 N），以及按升序位置 (N−1)p 线性插值的 90% 分位数。',['K','K']),
 ('D19','燃料线功率裕量','power','table','用已有的相邻线功率样点，线性插值求燃料峰温刚达到 1350 K 的线功率，同时插值该工况的包壳体积加权平均温度。',['W/m','K']),
 ('D20','中心孔几何设计取舍','size','table','比较最小、最大中心孔半径的方案。求燃料截面积从前者至后者的减少百分数，以及孔壁实际温度的降低量。',['%','K']),
]
frames={'P09':(['432000'],['Cs']),'P10':(['1'],['T']),'P11':(['1'],['sigma']),'P12':(['1'],['sigma']),
        'P13':(['100'],['T']),'P14':(['1e+08','2e+08'],['fastFluence']),'P16':([str(5000*i) for i in range(1,11)],['Cs'])}
columns={'D17':['E_inner_GPa','u_interface_um'],'D18':['h_W_m2K','fuel_T_max_K'],'D19':['lhgr_W_per_m','fuel_T_max_K','cladding_T_volavg_K'],'D20':['r_hole_mm','fuel_area_m2','T_hole_wall_K']}
