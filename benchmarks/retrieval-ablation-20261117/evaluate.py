"""Rank every candidate and score the frozen known-target queries without tuning."""
import argparse,csv,hashlib,json,math,re,sys,time
from collections import Counter
from pathlib import Path
import numpy as np

ARMS={'A':'原始输入卡向量','B':'工程描述卡向量','C':'描述向量＋九分面','D':'描述卡 BM25'}
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def tokenize(text):return [t for t in re.findall(r'[a-z0-9]+',text.lower()) if t not in {'the','a','an','of','for','and','or','to','in','with','case','offbeat'}]

def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args();root=args.root.resolve()
 sys.path.insert(0,str(root/'frozen'));import query as rq
 frozen=json.loads((root/'freeze-manifest.json').read_text());integrity={name:sha(root/'frozen'/name)==value for name,value in frozen['files'].items()};assert all(integrity.values())
 corpus=json.loads((root/'frozen/corpus.json').read_text());queries=json.loads((root/'frozen/queries.json').read_text());qrels=json.loads((root/'frozen/qrels.json').read_text());taxonomy=json.loads((root/'frozen/taxonomy.json').read_text());mappings=json.loads((root/'mapping/mappings.json').read_text())
 arrays=np.load(root/'embeddings.npz');cards=corpus['cards'];paths=[x['card_path'] for x in cards];N=len(paths)
 assert N==137 and len(queries)==len(mappings)==len(arrays['queries'])==32
 norms={name:float(np.max(np.abs(np.linalg.norm(arrays[name],axis=1)-1))) for name in ['queries','raw','descriptions']};assert max(norms.values())<1e-5
 raw_sim=arrays['queries']@arrays['raw'].T;desc_sim=arrays['queries']@arrays['descriptions'].T
 raw_scores=np.stack([raw_sim[:,arrays['raw_case_indices']==i].max(axis=1) for i in range(N)],axis=1)
 b_scores=np.stack([desc_sim[:,arrays['description_case_indices']==i].max(axis=1) for i in range(N)],axis=1)
 docs=[Counter(tokenize(c['retrieval_text'])) for c in cards];lengths=[sum(x.values()) for x in docs];avg=sum(lengths)/N
 results=[];rankings=[];durations=[]
 for qi,q in enumerate(queries):
  began=time.perf_counter();a={path:float(raw_scores[qi,i]) for i,path in enumerate(paths)};b={path:float(b_scores[qi,i]) for i,path in enumerate(paths)}
  tax,matched=rq._taxonomy_scores(taxonomy,mappings[q['id']]);bnorm=rq._normalize_scores(b)
  c={path:rq.EMBEDDING_WEIGHT*bnorm[path]+rq.TAXONOMY_WEIGHT*tax.get(path,0) for path in paths} if tax else b.copy()
  terms=set(tokenize(q['text']));df={t:sum(t in doc for doc in docs) for t in terms};d={}
  for path,doc,length in zip(paths,docs,lengths):
   d[path]=sum(math.log(1+(N-df[t]+.5)/(df[t]+.5))*doc[t]*2.2/(doc[t]+1.2*(.25+.75*length/max(avg,1))) for t in terms if doc[t])
  arm_scores={'A':a,'B':b,'C':c,'D':d};all_ranks={};rel=qrels[q['id']]
  for arm,scores in arm_scores.items():
   # All-zero lexical queries return no evidence instead of arbitrary tied hits.
   ordered=sorted((x for x in paths if arm!='D' or scores[x]>0),key=lambda x:(-scores[x],x))
   all_ranks[arm]=ordered;rank=next((i+1 for i,path in enumerate(ordered) if path in rel['targets']),None)
   result={'query_id':q['id'],'intent':q['intent'],'language':q['language'],'arm':arm,'target_rank':rank,'hit1':int(rank is not None and rank<=1),'hit3':int(rank is not None and rank<=3),'hit5':int(rank is not None and rank<=5),'reciprocal_rank':1/rank if rank else 0,'hard_negative_at5':int(bool(set(ordered[:5])&set(rel['hard_negatives']))),'retrieved_count':len(ordered),'top1':ordered[0] if ordered else '', 'target':';'.join(rel['targets'])}
   results.append(result)
   for i,path in enumerate(ordered):rankings.append({'query_id':q['id'],'arm':arm,'rank':i+1,'card_path':path,'score':scores[path],'description_cosine':b[path],'taxonomy_score':tax.get(path,0),'known_target':int(path in rel['targets']),'hard_negative':int(path in rel['hard_negatives'])})
  durations.append({'id':q['id'],'wall_ms':1000*(time.perf_counter()-began)})
 summary={}
 for language in ['en','zh','all']:
  summary[language]={}
  for arm in ARMS:
   rows=[r for r in results if r['arm']==arm and (language=='all' or r['language']==language)];count=len(rows)
   summary[language][arm]={'queries':count,**{k:sum(x[k] for x in rows)/count for k in ['hit1','hit3','hit5','reciprocal_rank','hard_negative_at5']},'zero_results':sum(r['retrieved_count']==0 for r in rows)}
 paired=[]
 for q in queries:
  rows={r['arm']:r for r in results if r['query_id']==q['id']}
  paired.append({'id':q['id'],'language':q['language'],'topic':qrels[q['id']]['topic'],'ranks':{arm:rows[arm]['target_rank'] for arm in ARMS},'B_to_C':('improved' if (rows['C']['target_rank'] or 138)<(rows['B']['target_rank'] or 138) else 'worsened' if (rows['C']['target_rank'] or 138)>(rows['B']['target_rank'] or 138) else 'unchanged')})
 mapping_meta=[json.loads(p.read_text()) for p in sorted((root/'mapping').glob('batch-*/run.json'))]
 tokens=Counter()
 for m in mapping_meta:tokens.update(m['tokens'])
 isolation=[json.loads(p.read_text()) for p in sorted((root/'mapping').glob('batch-*/workspace/isolation-check.json'))]
 assert len(isolation)==4 and all(x['passed'] for x in isolation) and sum(x['tool_calls'] for x in mapping_meta)==0
 embeddings=json.loads((root/'embedding-manifest.json').read_text());assert embeddings['embeddings_sha256']==sha(root/'embeddings.npz')
 report={'schema':'retrieval-ablation-results.v1','arms':ARMS,'summary':summary,'paired':paired,'mapper':{'batches':len(mapping_meta),'model_requests':sum(m['assistant_messages'] for m in mapping_meta),'tool_calls':sum(m['tool_calls'] for m in mapping_meta),'sum_wall_seconds':sum(m['wall_seconds'] for m in mapping_meta),'tokens':dict(tokens)},'embedding':embeddings,'integrity':{'frozen_files_unchanged':integrity,'unit_norm_max_error':norms,'B_C_same_query_and_description_vectors':True,'qrels_and_corpus_denied_to_mapper':all(x['passed'] for x in isolation),'all_137_cases_covered':True,'solver_starts':0,'frontend_agent_starts':0,'coverage_promotion':False,'query_rewriting':False},'ranking_seconds':sum(x['wall_ms'] for x in durations)/1000}
 save(root/'metrics.json',report);save(root/'query-results.json',results);save(root/'rankings.json',rankings)
 for name,rows in [('query-results.csv',results),('rankings.csv',rankings)]:
  with (root/name).open('w',newline='',encoding='utf-8-sig') as out:
   writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
 for lang,metrics in summary.items():print(json.dumps({'language':lang,'metrics':metrics},ensure_ascii=False),flush=True)
 print(json.dumps({'mapper':report['mapper'],'integrity':report['integrity']},ensure_ascii=False))

if __name__=='__main__':main()
