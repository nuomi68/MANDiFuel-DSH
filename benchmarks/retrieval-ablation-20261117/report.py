"""Build a standalone HTML review and publication-exportable scientific figure."""
import argparse,html,json
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args();root=args.root.resolve()
 metrics=json.loads((root/'metrics.json').read_text());results=json.loads((root/'query-results.json').read_text());rankings=json.loads((root/'rankings.json').read_text());queries=json.loads((root/'frozen/queries.json').read_text());qrels=json.loads((root/'frozen/qrels.json').read_text());maps=json.loads((root/'mapping/mappings.json').read_text());arms=metrics['arms']
 def esc(s):return html.escape(str(s))
 def pct(x):return f'{100*x:.1f}%'
 def table(lang):
  rows=[]
  for a,m in metrics['summary'][lang].items():
   rows.append('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in [a+' '+arms[a],f"{round(m['hit1']*m['queries'])}/{m['queries']} ({pct(m['hit1'])})",pct(m['hit3']),pct(m['hit5']),f"{m['reciprocal_rank']:.3f}",m['zero_results']])+'</tr>')
  return '<table><thead><tr>'+''.join('<th>'+x+'</th>' for x in ['方法','Hit@1','Hit@3','Hit@5','MRR','空结果数'])+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table>'
 rows=[]
 for pair in metrics['paired']:
  rows.append('<tr data-language="'+pair['language']+'"><td>'+pair['id']+'</td><td>'+esc(pair['topic'])+'</td>'+''.join('<td>'+str(pair['ranks'][a] or '未检出')+'</td>' for a in arms)+'<td>'+{'improved':'改善','worsened':'下降','unchanged':'相同'}[pair['B_to_C']]+'</td></tr>')
 cases=[]
 for q in queries:
  cards=[]
  for a in arms:
   top=[r for r in rankings if r['query_id']==q['id'] and r['arm']==a and r['rank']<=5]
   cards.append('<div class="arm"><strong>'+a+' '+arms[a]+'</strong><ol>'+''.join('<li class="'+('target' if x['known_target'] else 'negative' if x['hard_negative'] else '')+'">'+esc(x['card_path'])+'</li>' for x in top)+'</ol></div>')
  selected={f:v for f,v in maps[q['id']]['mapped_labels'].items() if v}
  cases.append('<details data-language="'+q['language']+'"><summary>'+q['id']+' · '+esc(qrels[q['id']]['topic'])+'</summary><p>'+esc(q['text'])+'</p><p>已知参考：<code>'+esc(', '.join(qrels[q['id']]['targets']))+'</code></p><div class="arms">'+''.join(cards)+'</div><p>自动映射（绿色为参考目标，红色为指定近邻）：</p><pre>'+esc(json.dumps(selected,ensure_ascii=False,indent=2))+'</pre></details>')
 mapper=metrics['mapper'];embed=metrics['embedding'];eng=metrics['summary']['en'];b=eng['B'];c=eng['C'];delta=c['hit1']-b['hit1']
 headline=f"英文主集：九分面融合相对描述卡向量，Top-1 命中率变化 {delta*100:+.2f} 个百分点；MRR 变化 {c['reciprocal_rank']-b['reciprocal_rank']:+.3f}。"
 count=lambda state:sum(x['B_to_C']==state for x in metrics['paired'] if x['language']=='en')
 body=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OFFBEAT 检索消融比较</title>
<style>body{{font:16px/1.65 system-ui,sans-serif;color:#203149;background:#f5f7fa;margin:0}}main{{max-width:1220px;margin:auto;padding:32px}}section,details{{background:white;border:1px solid #d9e1eb;border-radius:12px;padding:20px;margin:20px 0}}h1{{font-size:28px}}h2{{font-size:21px}}.note{{border-left:4px solid #4777b2;padding:12px 18px;background:#eef4fb}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid #e0e7ee}}th{{background:#edf2f8}}.scroll{{overflow:auto}}.arms{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}.arm{{border:1px solid #e0e7ee;padding:14px;border-radius:8px;overflow-wrap:anywhere;font-size:13px}}.target{{color:#167344;font-weight:bold}}.negative{{color:#b34737}}summary{{cursor:pointer;font-weight:600}}pre{{white-space:pre-wrap;font-size:13px;overflow-wrap:anywhere;background:#f6f8fa;padding:12px}}code{{overflow-wrap:anywhere}}img{{width:100%;height:auto}}button{{padding:9px 15px;margin:6px;border:1px solid #bbcbdc;border-radius:7px;background:white;cursor:pointer}}small{{color:#62758b}}@media(max-width:700px){{main{{padding:12px}}.arms{{grid-template-columns:1fr}}}}</style>
<main><h1>OFFBEAT 案例检索：输入卡、描述卡与九分面比较</h1><p>{esc(headline)}</p><p class="note">137 个候选；16 类工程意图，各有中英文表述，共32条查询。问题、参考目标和融合权重均在排序前冻结。本次是探索性检索实验，不是求解正确率实验。</p>
<section><h2>比较设置</h2><p>A：原始输入字典分块向量＋余弦；B：工程描述卡向量＋余弦；C：与B完全相同的查询和描述向量，叠加既有九分面评分；D：同一描述语料的BM25辅助组。</p><p>统一调用 DashScope <code>text-embedding-v3</code>，1024维，全部重新嵌入。原始输入保留注释、相对文件名，不加入案例路径或标签。{embed['input_files']}个原始文件，{embed['encoding']['raw']['vectors']}个原始片段；每片最多6000 UTF-8字节，重叠800字节，按案例取最大片段余弦。长输入没有只截取开头。</p><p>C固定采用0.35×描述余弦的候选内min-max归一化＋0.65×九分面评分，置信度门槛0.5，沿用原有分面权重。未启用查询改写或多几何覆盖提升，因而B与C只相差结构化排序项。</p></section>
<section><h2>英文主集 · 16条</h2><div class="scroll">{table('en')}</div><p>B→C参考目标名次：改善{count('improved')}条，下降{count('worsened')}条，相同{count('unchanged')}条。</p><img src="retrieval-comparison.png" alt="英文主集的Top-1、Top-5与MRR比较"></section>
<section><h2>中文同义集 · 16条</h2><div class="scroll">{table('zh')}</div><p>中文是同一16类意图的配对表述，不应将32条当成32个独立任务。BM25沿用现有ASCII词项切分，中文结果仅作语言适配诊断，不用于放大主结论。</p></section>
<section><h2>成本与适用范围</h2><p>九分面映射使用原生DSH的DeepSeek V4 Flash高推理档，4批共{mapper['model_requests']}次模型响应，{mapper['tokens'].get('totalTokens',0):,} tokens，工具调用{mapper['tool_calls']}次。映射进程通过Landlock禁止读取qrels、任务参考标注与案例语料，仅获得问题和受控词表。高推理档的本次独立映射有明显额外开销，本轮不支持“九分面更省token”的结论。</p><p>嵌入成功{embed['provider_batches']}批，已知输入{embed['provider_input_tokens']:,} tokens，含全部三组所需的语料和查询；相同输入先按文本去重。另一次响应发生IncompleteRead，未获得usage，故上述token数是可观测下界；只重试缺失输入，见<a href="embedding-network-incident.json">网络失败记录</a>。索引编码与查询映射为两类不同开销，不与先前科学计算Skill的节省率合并。</p><p>参考目标由本次实验作者依据现有案例用途构造，未穷举所有可改造的相关案例。Hit@k表示已知参考是否进入前k，MRR为首个已知参考的倒数排名；不能写成完整相关集召回率，也不能据此宣称普遍优于向量检索。九分面包含接近案例身份的sibling标签，收益不能全部归于几何或物理字段。</p><p>未运行求解器、科学计算agent或前端agent。保留全部失败与退化结果，未根据本集命中情况调权。API模型版本由服务方管理，本地保存请求ID、精确文本哈希和返回向量以便复核。</p></section>
<section><h2>逐题参考名次</h2><button onclick="filterLanguage('all')">全部</button><button onclick="filterLanguage('en')">英文</button><button onclick="filterLanguage('zh')">中文</button><div class="scroll"><table><thead><tr><th>查询</th><th>意图</th><th>A</th><th>B</th><th>C</th><th>D</th><th>B→C</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
<section><h2>Top-5与自动映射复核</h2>{''.join(cases)}</section>
<section><h2>复核文件</h2><p><a href="metrics.json">完整指标与完整性检查</a> · <a href="audit.json">独立复核</a> · <a href="query-results.csv">逐题CSV</a> · <a href="rankings.csv">全候选排名CSV</a> · <a href="frozen/queries.json">冻结问题</a> · <a href="frozen/qrels.json">冻结参考</a> · <a href="protocol-amendment.json">用户指定DashScope后的协议修订</a> · <a href="embedding-manifest.json">嵌入调用记录</a> · <a href="retrieval-comparison.svg">可编辑SVG图</a></p><p>接口说明：<a href="https://www.alibabacloud.com/help/en/model-studio/embedding-interfaces-compatible-with-openai">阿里云官方Embedding文档</a>。</p></section></main><script>function filterLanguage(v){{document.querySelectorAll('[data-language]').forEach(x=>x.hidden=v!=='all'&&x.dataset.language!==v)}}</script></html>'''
 (root/'comparison.html').write_text(body)
 import matplotlib
 matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 from matplotlib.font_manager import FontProperties
 import numpy as np
 font=FontProperties(fname=str(Path(__file__).resolve().parents[2]/'frontend/assets/fonts/workbench-cjk.ttf'))
 plt.rcParams.update({'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})
 fig,axs=plt.subplots(1,2,figsize=(11,4.5),gridspec_kw={'width_ratios':[1.6,1]});labels=list(arms);x=np.arange(4)
 for off,key,label,color in [(-.18,'hit1','Top-1','#3b70ad'),(.18,'hit5','Top-5','#78aeae')]:
  bars=axs[0].bar(x+off,[eng[a][key]*100 for a in labels],.34,label=label,color=color);axs[0].bar_label(bars,fmt='%.1f',padding=3,fontsize=9)
 axs[0].set_ylim(0,112);axs[0].set_ylabel('已知参考命中率 (%)',fontproperties=font);axs[0].legend(loc='upper left',frameon=False)
 bars=axs[1].bar(x,[eng[a]['reciprocal_rank'] for a in labels],.65,color=['#8e9bb0','#3b70ad','#a376ba','#78aeae']);axs[1].bar_label(bars,fmt='%.3f',padding=3,fontsize=9);axs[1].set_ylim(0,1.12);axs[1].set_ylabel('MRR')
 for ax in axs:
  ax.set_xticks(x,['A 原始卡','B 描述卡','C 九分面','D BM25'],fontproperties=font,fontsize=10);ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
 fig.suptitle('OFFBEAT 检索比较 · 137个候选 / 16条英文查询',fontproperties=font,fontsize=15);fig.tight_layout();fig.savefig(root/'retrieval-comparison.png',dpi=180,bbox_inches='tight');fig.savefig(root/'retrieval-comparison.svg',bbox_inches='tight');plt.close(fig)
 print(json.dumps({'report':str(root/'comparison.html'),'headline':headline},ensure_ascii=False))

if __name__=='__main__':main()
