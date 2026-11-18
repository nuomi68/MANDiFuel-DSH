"""Freeze retrieval-only experiment definition before producing rankings."""
import hashlib,json,shutil,subprocess
from datetime import datetime,timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parent.parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')

def main():
 import argparse
 p=argparse.ArgumentParser();p.add_argument('output',type=Path);args=p.parse_args()
 root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
 frozen=root/'frozen';frozen.mkdir()
 for name,src in [('corpus.json',REPO/'rag/data/offbeat_case_cards_compact_138.json'),('taxonomy.json',REPO/'rag/index/taxonomy_index.json'),('vocabulary.json',REPO/'rag/index/vocabulary.json'),('tasks.json',HERE/'tasks.json'),('query.py',REPO/'rag/query.py'),('build_index.py',REPO/'rag/build_index.py'),('providers.py',REPO/'rag/providers.py')]:shutil.copyfile(src,frozen/name)
 cards=json.loads((frozen/'corpus.json').read_text())['cards'];paths={c['card_path'] for c in cards}
 tasks=json.loads((frozen/'tasks.json').read_text())['intents'];queries=[];qrels={}
 for t in tasks:
  assert set(t['targets']+t['hard_negatives'])<=paths,t['id']
  for lang in ['en','zh']:
   qid=t['id']+'-'+lang
   queries.append({'id':qid,'intent':t['id'],'language':lang,'text':t[lang]})
   qrels[qid]={'targets':t['targets'],'hard_negatives':t['hard_negatives'],'topic':t['topic']}
 save(frozen/'queries.json',queries);save(frozen/'qrels.json',qrels)
 design={
  'schema':'retrieval-ablation-design.v1','frozen_at_utc':datetime.now(timezone.utc).isoformat(),
  'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
  'candidate_count':len(cards),'independent_intents':len(tasks),'queries':len(queries),
  'embedding':{'provider':'DashScope','base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1','model':'text-embedding-v3','dimension':1024,'normalization':'L2 for cosine','query_prefix':None,'document_prefix':None,'query_rewrite':False},
  'chunking':{'max_utf8_bytes':6000,'overlap_utf8_bytes':800,'raw_aggregation':'maximum chunk cosine per case','description_aggregation':'maximum chunk cosine per case; same splitting if necessary'},
  'raw_inputs':{'include':['0/**','constant/**','system/**','rodDict','sphereDict','rod3Ddict.json','input_settings.txt'],'exclude':['polyMesh/**','dynamicCode/**','postProcessing/**','binary/non-UTF8','log*','*.log','generated results/time directories','Allrun and analysis scripts'],'max_bytes_per_file':200000,'comments':'preserved','case_path_metadata':'not injected; relative input filenames retained'},
  'arms':{'A':'raw input dictionaries, chunk embeddings, cosine','B':'published retrieval_text, embeddings, cosine','C':'exact same B vectors and original query vectors; existing minmax normalization and fixed 0.35 embedding + 0.65 taxonomy fusion','D':'BM25 on exact same description text as B, no injected JSON labels'},
  'taxonomy':{'threshold':0.5,'weights':'frozen query.py FACET_WEIGHTS','query_mapper':'DeepSeek V4 Flash via native headless DSH; query and controlled vocabulary only; no qrels, no case corpus; no tools','coverage_promotion':False,'fallback_on_no_accepted_labels':'B ranking'},
  'bm25':{'tokenizer':'existing ASCII [a-z0-9]+ and existing stopwords','k1':1.2,'b':0.75},
  'metrics':['known-target Hit@1','known-target Hit@3','known-target Hit@5','known-target MRR over all 137','hard-negative presence@5'],
  'primary':'16 English queries; 16 Chinese paraphrases reported separately; 32 combined descriptive only',
  'limitations':['Exploratory author-constructed dataset; preferred-reference targets are not exhaustive relevance judgments.','Chinese paraphrases are paired, not independent extra samples.','Unified DashScope text-embedding-v3 1024-dimensional vectors, regenerated for every arm.','No tuning on observed rankings. No solver, science agent or frontend. Mapping overhead reported separately.']
 }
 save(frozen/'design.json',design)
 save(root/'freeze-manifest.json',{'frozen_at_utc':design['frozen_at_utc'],'files':{p.name:sha(p) for p in sorted(frozen.iterdir())}})
 print(json.dumps({'output':str(root),'candidates':len(cards),'queries':len(queries),'frozen':True}))

if __name__=='__main__':main()
