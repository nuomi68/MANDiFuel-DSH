#!/usr/bin/env python3
"""补充中文压缩动作词典，保留原描述、参数和原始行号；不导出内部推理。"""
import json
from pathlib import Path
import re
import subprocess
import sys

REPO=Path(__file__).resolve().parents[2]
SPECIFIC={
'Run reference case 1a with offbeat':'原样运行参考 case_1a（尚非目标参数）',
'Run additional sensitivity cases':'追加网格密度与楔角敏感性求解',
'Run case B and sensitivity cases':'运行 80 MPa 工况及附加敏感性工况',
'Run 120-cell mesh refinement case':'追加 120 单元网格计算',
'Run test_d1 and inspect D/source':'短算诊断 d1 绑定，并查看实际扩散与生成源',
'Test constant d1 and C0 override in reference case':'在参考副本中测试常 D 与初始浓度绑定',
'Final clean end-to-end run of target case':'从头重跑目标计算与后处理',
'Final end-to-end run with all post-processing':'重跑目标计算及完整后处理',
'Final rerun with mesh-radius check':'加入半径核对后再次重跑目标计算',
'Run target case end-to-end':'执行目标算例完整计算与后处理',
'Prepare and run target case via parameter plan':'通过参数计划联动准备并执行目标算例',
'Run capability check on prepared case':'对目标输入补做软件能力检查',
'Query capabilities for Cs transport entries':'按 Cs 输运参数名查询能力表',
'Query capabilities and list local docs':'按具体模型名查询能力表并列出本地手册',
'Query pressure BC and cylindrical stress facts':'按边界、应力及楔形名称查询能力表',
'Query capability table for solver selectors':'批量查询模型选择器能力事实',
'Query heatSource, material, rheology, sliceMapper facts':'查询热源、材料、本构和切片映射能力',
'Show transport capability topic':'查询已收录的输运主题',
'Inspect capabilities CLI usage':'查询能力表命令行用法与摘要',
'Inspect RAG query tool header':'查看共享检索工具脚本头部实现',
'Read offbeat wrapper script and config':'读取实验求解包装器实现与配置',
'Copy reference case into workspace':'将自行选定的参考输入复制到工作区',
'Copy reference input files into workspace':'复制检索选定的参考输入',
'Copy selected reference case for provenance':'保存选中参考输入以记录来源',
'Copy reference case 1a and check tools':'复制参考 case_1a 并检查工具',
'Copy shared fixed-study controller template':'复制固定研究控制器模板',
'Copy fixed-study template':'复制固定研究模板',
'Build template, read back, run mesh preflight':'构建目标模板、原生回读并预检网格',
'Generate coarse mesh dictionary with reference rodMaker':'用现成 rodMaker 生成粗网格字典',
'Generate fine mesh, run blockMesh and checkMesh':'生成细网格并执行网格生成与检查',
'Generate and check the spherical wedge mesh':'生成并检查球形楔网格',
'Test sphereMaker with kernel-only geometry':'测试现成 sphereMaker 的纯球核输入',
'Run fixed study with both meshes':'运行粗细两网格的固定研究',
'Run the two-point fixed study':'运行两个压力点的固定研究',
'Build and run main case A (40 MPa)':'构建并运行 40 MPa 球壳工况',
'Build final main cases A and B':'构建最终两压力工况',
'Run first RAG retrieval query':'执行第一次离线 RAG 检索',
'Run second RAG retrieval query':'执行第二次离线 RAG 检索',
'Run first RAG query for heat conduction cases':'离线检索适合导热的参考输入',
'Run local RAG retrieval for spherical shell cases':'离线检索受压球壳参考输入',
'Query local RAG for sphere Cs diffusion references':'离线检索球核 Cs 扩散参考输入',
'Run RAG query 1 (English)':'用英文关键词执行第一次 RAG 检索',
'Run queries 2 and 3 and summarize all':'执行补充检索并汇总候选',
'Save RAG result and summarize candidates':'保存检索原文并汇总候选',
'Save second RAG query output':'保存第二次检索原文',
'Summarize RAG query 1 results':'汇总首次检索候选',
'Second RAG query on pressure verification cases':'补充检索压力验证参考',
'Second targeted RAG query and compact display':'执行第二次定向检索并精简显示',
'Cross-check plan profile vs my extraction':'比较公共计划输出与自行提取的剖面',
'Run physical consistency validation':'核对实际场的物理一致性',
'Set outer radial coordinate exactly 350 um':'将球核输入的外半径坐标设为 350 μm',
'Wire subprocess import and owner_zone arguments':'修正任务脚本导入与公共接口 owner_zone 参数',
'Fix time selector and re-collect results':'修正时刻选择后重提取，复用已有求解',
'Re-run collect to extract results without new solves':'复用已有求解并重新收集结果',
'Re-run study to collect reporting and write report':'复用研究记录并收集报告数据',
'Regenerate report from retained responses':'用保留响应重新生成报告',
'Reproduce and preserve lineUniform input failure log':'复现并保留旧采样类型失败日志',
'Rerun coarse solver with extended lhgr table':'延长功率表末点后重跑粗网格求解',
'Regenerate inputs and rerun coarse solver':'修改输入后重新运行粗网格求解',
'Preserve failed coarse run log and input':'保留失败粗网格运行的输入与日志',
'Fix radial sign convention and rerun':'修正径向正负号说明并重新处理',
'Fix eigenvalue statement and review report tail':'修正特征值表述并查看报告结尾',
'Fix sensitivity run count':'修正附加敏感性运行次数记录',
'Correct field list in report':'修正报告中的字段清单',
'Soften reference default-mechanism claim':'修正对参考默认机制的过度表述',
'Locate stale comment in sphereDict':'定位球核参数文件中过期的注释',
'Note benign deprecation warnings':'记录未影响请求结果的弃用警告',
'Polish sign-convention paragraph':'完善正负号与坐标约定说明',
'Fix SVG padding and regenerate plots':'调整图像边距并重新生成图表',
'Validate SVG XML and CSV shapes':'核对图像语法与表格行列结构',
}


def compressed(description):
 text=description.lower();topics=[]
 rules=[
 (r'rag|retriev|query|candidate','离线检索、候选或查询入口'),
 (r'capabilit|public tool','软件能力与公共接口'),
 (r'checkmesh|mesh|blockmesh|cellzone|geometry|cell centre|cell center|points|faces','几何、网格与分区'),
 (r'diffcs|sourcecs|d1|diffusiv|fissionproduct|fission product|fpdiffusion|cs ','Cs 扩散模型、参数与实际场'),
 (r'inventory|release|volum','库存或体积积分'),
 (r'sigma|stress|strain|eigenvalue|radial sign','应力、应变与坐标基底'),
 (r'thermal|temperature|heat|lhgr|gap|conductiv|alpha','温度、热源与界面换热'),
 (r'sphere|spherical|wedge|triso|hollowsphere','球形模型与楔形约定'),
 (r'profile|surface|patch|boundary','剖面、表面或边界响应'),
 (r'study|controller|prepare\(|point|plan','算例准备与研究编排'),
 (r'account|ledger|execution|provenance|evidence|solver log|warning|convergence|iteration','执行凭据、日志或收敛'),
 (r'plot|svg|png|figure|matplotlib|axis tick|eigenvalue splitting','图表生成与显示'),
 (r'report|summary|readme|table|csv|json|results|comment','结果表、说明与报告'),
 (r'manual|doc|reference|ref-run|case1|case_1|case_3|case_10','本地说明或参考输入'),
 (r'workspace|permission|files|listing|binary|binaries|tools|env|path','工作区、文件或运行环境'),
 ]
 for pattern,label in rules:
  if re.search(pattern,text):topics.append(label)
 topics=topics[:2] or ['本题输入与计算产物']
 verb=description.split()[0].lower() if description else ''
 verbs={'read':'读取','inspect':'查看','show':'显示','view':'查看','review':'复查','print':'显示','check':'检查','verify':'核对','validate':'验证','confirm':'确认','inventory':'列出','list':'列出','explore':'查看','find':'查找','locate':'定位','search':'搜索','grep':'搜索','query':'查询','run':'执行','rerun':'重新执行','re-run':'重新执行','retry':'重试','test':'试用','copy':'复制','re-copy':'重新复制','create':'创建','build':'构建','generate':'生成','regenerate':'重新生成','extract':'提取','integrate':'积分核对','compare':'比较','diff':'比较差异','analyze':'分析','collect':'汇总','capture':'保存','assemble':'汇集','record':'记录','save':'保存','preserve':'保留','fix':'修正','correct':'修正','rewrite':'改写','update':'更新','extend':'补充','apply':'修改','patch':'修改','wire':'修正','normalize':'统一','make':'设置','remove':'清理','note':'说明','soften':'修正','polish':'完善','refine':'调整','set':'设置','add':'补充','sync':'同步','complete':'补齐','comprehensive':'全面核对','final':'最后核对','second':'补充检索'}
 action=verbs.get(verb,'处理')+'：'+'；'.join(topics)
 identifiers=[]
 for token in re.findall(r'\b(?:case_\w+|case1\w*|test_d1|solverDict|controlDict|rodDict|sphereDict|blockMeshDict|fvSchemes|fvSolution|cellZones|systemPressure|resistiveGap|lineUniform|owner_zone|sigmaSph|sigmaCyl|diffCs|sourceCs|FpDiffusion|checkMesh|rodMaker|sphereMaker)\b',description):
  if token not in identifiers:identifiers.append(token)
 if identifiers:action+='（'+', '.join(identifiers[:3])+'）'
 if re.search(r'120.cell',text):action+='〔120单元〕'
 if 'coarse' in text:action+='〔粗网格〕'
 elif 'fine mesh' in text or 'fine results' in text:action+='〔细网格〕'
 if 'case a' in text or '40 mpa' in text:action+='〔40 MPa〕'
 if 'case b' in text or '80 mpa' in text:action+='〔80 MPa〕'
 return action


def main():
 r=Path(sys.argv[1]).resolve();p=r/'trace-descriptions.zh.json';translations=json.loads(p.read_text());count=0
 for path in r.glob('*/*/traces/**/session.jsonl'):
  for line in path.open():
   e=json.loads(line)
   if e.get('type')!='tool/call' or e['data']['name']!='bash':continue
   a=e['data']['arguments'];a=json.loads(a) if isinstance(a,str) else a;description=a.get('description','')
   if description in translations or re.search(r'[\u4e00-\u9fff]',description):continue
   translations[description]=SPECIFIC.get(description,compressed(description));count+=1
 p.write_text(json.dumps(translations,ensure_ascii=False,indent=2)+'\n')
 subprocess.run(['python3','-B',str(REPO/'benchmarks/candidate-pairs/render_compact_traces_zh.py'),str(r),'--translations',str(p)],check=True)
 manifest=r/'中文单行轨迹/翻译清单.json';v=json.loads(manifest.read_text());v['动作处理']='关键动作逐项翻译，其他动作按可观察操作、对象、文件/API名压缩为中文；完整原描述与命令保留在工具参数和原始轨迹中，不导出内部推理。';v['本轮新增动作词条']=count;manifest.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
