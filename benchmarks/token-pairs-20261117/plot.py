"""Export the measured comparison as a standalone report figure."""
import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

p=argparse.ArgumentParser();p.add_argument('run_root',type=Path);args=p.parse_args();root=args.run_root.resolve();data=json.loads((root/'comparison.json').read_text());repo=Path(__file__).resolve().parents[2]
font=FontProperties(fname=str(repo/'frontend/assets/fonts/workbench-cjk.ttf'))
plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'path'})
fig,axes=plt.subplots(1,2,figsize=(12,4.6));colors=['#8a98aa','#3465c6'];x=list(range(3));width=.34
for ax,key,unit,title in [(axes[0],'total_tokens',1e6,'总 Token（含缓存输入）'),(axes[1],'tool_calls',1,'工具调用次数')]:
    for j,arm in enumerate(['bare','skill']):
        values=[t['arms'][arm][key]/unit for t in data['tasks'].values()];positions=[i+(j-.5)*width for i in x];bars=ax.bar(positions,values,width,color=colors[j],label='裸 DSH' if arm=='bare' else '科学计算 Skills')
        for b,v in zip(bars,values):ax.text(b.get_x()+b.get_width()/2,v+max(values)*.025,f'{v:.2f}' if unit>1 else f'{v:g}',ha='center',va='bottom',fontsize=10)
    ax.set_xticks(x,['T01\n关联尺寸准备','T02\n单工况与多响应','T03\n三点参数扫描'],fontproperties=font)
    ax.set_title(title,fontproperties=font,pad=16);ax.set_ylabel('百万 Token' if unit>1 else '次',fontproperties=font);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);ax.set_ylim(0,ax.get_ylim()[1]*1.17);ax.legend(prop=font,frameon=False,loc='upper left')
fig.suptitle('科学计算 Skills 与裸 DSH：三任务成对测试',fontproperties=font,fontsize=16,y=1.02)
fig.text(.5,-.025,'同模型、同输入，无前端；每任务每组一次。六组均通过交付一致性核验。',fontproperties=font,ha='center',fontsize=10,color='#526173')
fig.tight_layout();fig.savefig(root/'token-comparison.png',dpi=180,bbox_inches='tight',facecolor='white');fig.savefig(root/'token-comparison.svg',bbox_inches='tight',facecolor='white');plt.close(fig)
print('Exported token-comparison.png and token-comparison.svg')
