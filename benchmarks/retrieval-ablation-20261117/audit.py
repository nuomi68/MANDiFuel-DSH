"""Independently check cached embeddings, chunk coverage and exported metrics."""
import argparse,csv,hashlib,json,math
from pathlib import Path
import numpy as np

def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args();root=args.root.resolve()
 queries=json.loads((root/'frozen/queries.json').read_text());qrels=json.loads((root/'frozen/qrels.json').read_text());cards=json.loads((root/'frozen/corpus.json').read_text())['cards'];desc=json.loads((root/'description-chunks.json').read_text());raw=[json.loads(s) for s in (root/'raw-chunks.jsonl').read_text().splitlines()];arrays=np.load(root/'embeddings.npz');summary=json.loads((root/'metrics.json').read_text())
 checks={};errors=[];models=set();vector_count=0
 for name,rows in [('queries',queries),('descriptions',desc),('raw',raw)]:
  assert len(rows)==len(arrays[name])
  for i,row in enumerate(rows):
   digest=hashlib.sha256(('text-embedding-v3|1024|'+row['text']).encode()).hexdigest();record=json.loads((root/'dashscope-cache'/(digest+'.json')).read_text());models.add(record['model'])
   assert record['input_sha256']==hashlib.sha256(row['text'].encode()).hexdigest()
   cached=np.asarray(record['embedding'],dtype=np.float32);cached/=np.linalg.norm(cached)
   assert np.allclose(arrays[name][i],cached,atol=1e-7),[name,i]
   if name!='queries':assert row['card_path']==cards[row['case_index']]['card_path']
   vector_count+=1
 checks['all_exported_vectors_match_exact_text_cache']=vector_count;checks['returned_models']=sorted(models);assert models=={'text-embedding-v3'}
 checks['no_chunk_exceeds_6000_utf8_bytes']=all(len(r['text'].encode())<=6000 for r in raw+desc)
 # Reassemble the union of byte intervals for every raw input file.
 groups={}
 for row in raw:
  marker=row['text'].split('\n',1)[0] if row['byte_start']==0 else None
  if marker is not None:current=(row['card_path'],marker);groups[current]=[]
  groups[current].append(row)
 for group in groups.values():
  end=0
  for r in group:
   assert r['byte_start']<=end;end=max(end,r['byte_end'])
  assert end==group[0]['source_bytes']
 checks['raw_files_without_missing_chunk_intervals']=len(groups)
 # Recompute ranks and summary values solely from the CSV rank exports.
 with (root/'rankings.csv').open(encoding='utf-8-sig') as stream:rankings=list(csv.DictReader(stream))
 with (root/'query-results.csv').open(encoding='utf-8-sig') as stream:results=list(csv.DictReader(stream))
 for row in results:
  ordered=[r for r in rankings if r['query_id']==row['query_id'] and r['arm']==row['arm']]
  rank=next((int(r['rank']) for r in ordered if r['card_path'] in qrels[row['query_id']]['targets']),None)
  assert row['target_rank']==('' if rank is None else str(rank))
  for k in [1,3,5]:assert int(row['hit'+str(k)])==int(rank is not None and rank<=k)
  assert math.isclose(float(row['reciprocal_rank']),1/rank if rank else 0)
 for lang in ['en','zh','all']:
  for arm in ['A','B','C','D']:
   selected=[r for r in results if r['arm']==arm and (lang=='all' or r['language']==lang)]
   for key in ['hit1','hit3','hit5','reciprocal_rank']:
    assert math.isclose(sum(float(r[key]) for r in selected)/len(selected),summary['summary'][lang][arm][key])
 checks['independent_csv_metric_recomputation']=True
 # Explain the low A score by inspecting actual winners, without changing A.
 examples=[]
 for qid in ['Q01-en','Q05-en','Q07-en','Q16-en']:
  qi=next(i for i,q in enumerate(queries) if q['id']==qid);sim=arrays['raw']@arrays['queries'][qi];winner=int(sim.argmax());target_indices=[i for i,r in enumerate(raw) if r['card_path'] in qrels[qid]['targets']];target=max(target_indices,key=lambda i:sim[i])
  examples.append({'id':qid,'winner':raw[winner]['card_path'],'winner_cosine':float(sim[winner]),'winner_input_preview':raw[winner]['text'][:400],'target_best_cosine':float(sim[target]),'target_best_input_preview':raw[target]['text'][:400]})
 report={'passed':True,'checks':checks,'low_raw_score_diagnostics':examples,'caveat':'Diagnostic only; no reranking, preprocessing tuning or qrel changes.'}
 (root/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'passed':True,'checks':checks},ensure_ascii=False))

if __name__=='__main__':main()
