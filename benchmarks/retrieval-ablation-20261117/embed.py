"""Encode every arm through DashScope, without a local embedding model."""
import argparse,hashlib,http.client,json,os,re,shlex,sys,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
import numpy as np

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def load_key():
 if os.environ.get('DASHSCOPE_API_KEY'):return os.environ['DASHSCOPE_API_KEY']
 for line in Path('/home/lwz/.bashrc').read_text().splitlines():
  m=re.match(r'\s*(?:export\s+)?DASHSCOPE_API_KEY\s*=\s*(.*)',line)
  if m:
   tokens=shlex.split(m[1],comments=True)
   if tokens and '$' not in tokens[0]:return tokens[0]
 raise RuntimeError('DASHSCOPE_API_KEY unavailable')

def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--case-library',type=Path,default=Path('/home/lwz/offbeat'));args=p.parse_args()
 root=args.root.resolve();began=time.monotonic();sys.path.insert(0,str(root/'frozen'));from providers import OpenAICompatibleClient,ProviderError
 corpus=json.loads((root/'frozen/corpus.json').read_text());queries=json.loads((root/'frozen/queries.json').read_text());design=json.loads((root/'frozen/design.json').read_text())
 amendment={'schema':'retrieval-ablation-amendment.v1','at_utc':datetime.now(timezone.utc).isoformat(),'reason':'Explicit user direction: use DASHSCOPE_API_KEY embedding; do not download a local embedding model. No rankings produced before amendment.','embedding':{'provider':'DashScope','base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1','model':'text-embedding-v3','dimension':1024,'prefix':None,'normalization':'L2 for cosine','fresh_embedding_all_arms':True},'chunking':{'max_utf8_bytes':6000,'overlap_utf8_bytes':800,'aggregation':'maximum chunk cosine per case for both raw and description'},'unchanged':['questions','preferred-reference qrels','137 candidates','four arms','taxonomy mappings and fixed fusion weights','metrics']}
 if not (root/'protocol-amendment.json').exists():
  assert not (root/'metrics.json').exists();save(root/'protocol-amendment.json',amendment)
 raw=[];desc=[];files=[];excluded=[];counts=[]
 def split(text):
  data=text.encode();lo=0
  while lo<len(data):
   hi=min(lo+6000,len(data))
   while hi<len(data) and data[hi]&0xc0==0x80:hi-=1
   yield data[lo:hi].decode(),lo,hi,len(data)
   if hi==len(data):break
   lo=max(lo+1,hi-800)
   while lo<len(data) and data[lo]&0xc0==0x80:lo+=1
 def add(target,text,index,path,kind):
  for body,lo,hi,total in split(text):target.append({'case_index':index,'card_path':path,'kind':kind,'byte_start':lo,'byte_end':hi,'source_bytes':total,'text':body})
 for index,card in enumerate(corpus['cards']):
  path=card['card_path'];source=args.case_library/path;assert source.is_dir(),path;candidates=[]
  for folder in ['0','constant','system']:
   if (source/folder).exists():candidates.extend(p for p in (source/folder).rglob('*') if p.is_file())
  for name in ['rodDict','sphereDict','rod3Ddict.json','input_settings.txt']:
   if (source/name).is_file():candidates.append(source/name)
  count=0;rawstart=len(raw)
  for file in sorted(set(candidates)):
   rel=file.relative_to(source).as_posix();reason=None
   if set(file.relative_to(source).parts)&{'polyMesh','dynamicCode','postProcessing'}:reason='generated_mesh_or_runtime'
   elif file.name.startswith('log') or file.suffix=='.log':reason='log'
   elif file.stat().st_size>design['raw_inputs']['max_bytes_per_file']:reason='size_limit'
   if reason:excluded.append({'card_path':path,'file':rel,'reason':reason});continue
   data=file.read_bytes()
   try:text=data.decode()
   except UnicodeDecodeError:excluded.append({'card_path':path,'file':rel,'reason':'non_utf8'});continue
   if '\x00' in text or re.search(r'\bformat\s+binary\s*;',text):excluded.append({'card_path':path,'file':rel,'reason':'binary'});continue
   if not text.strip():continue
   files.append({'card_path':path,'file':rel,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
   add(raw,'Input file: '+rel+'\n'+text,index,path,'raw');count+=1
  add(desc,card['retrieval_text'],index,path,'description');counts.append({'card_path':path,'input_files':count,'raw_chunks':len(raw)-rawstart})
 assert all(c['raw_chunks'] for c in counts)
 save(root/'input-file-manifest.json',{'files':files,'excluded':excluded,'cases':counts})
 with (root/'raw-chunks.jsonl').open('w') as out:
  for x in raw:out.write(json.dumps(x,ensure_ascii=False)+'\n')
 save(root/'description-chunks.json',desc)
 cache=root/'dashscope-cache';cache.mkdir(exist_ok=True)
 client=OpenAICompatibleClient(base_url=amendment['embedding']['base_url'],model='text-embedding-v3',api_key=load_key(),dimension=1024,timeout_seconds=120)
 records=[('queries',i,x) for i,x in enumerate(queries)]+[('descriptions',i,x) for i,x in enumerate(desc)]+[('raw',i,x) for i,x in enumerate(raw)]
 by_hash={};text_keys={}
 for name,i,x in records:
  digest=hashlib.sha256(('text-embedding-v3|1024|'+x['text']).encode()).hexdigest();by_hash[digest]=x['text'];text_keys[name,i]=digest
 pending=[d for d in by_hash if not (cache/(d+'.json')).exists()]
 telemetry=[json.loads(p.read_text()) for p in sorted(cache.glob('batch-*.meta.json'))]
 previous_batches=len(telemetry);offset=max((x['batch'] for x in telemetry),default=0)
 batches=[pending[i:i+10] for i in range(0,len(pending),10)]
 def run_batch(item):
  number,digests=item;start=time.monotonic();attempts=[]
  for attempt in range(4):
   try:
    response=client._post('embeddings',{'model':'text-embedding-v3','input':[by_hash[d] for d in digests],'dimensions':1024,'encoding_format':'float'});break
   except (ProviderError,http.client.HTTPException) as exc:
    attempts.append({'attempt':attempt+1,'error':str(exc)})
    if attempt==3:raise
    time.sleep(2**attempt)
  data=sorted(response['data'],key=lambda x:x['index']);assert len(data)==len(digests)
  for digest,row in zip(digests,data):
   vector=row['embedding'];assert len(vector)==1024 and all(np.isfinite(vector))
   save(cache/(digest+'.json'),{'embedding':vector,'input_sha256':hashlib.sha256(by_hash[digest].encode()).hexdigest(),'model':response.get('model'),'dimension':1024})
  meta={'batch':number,'rows':len(digests),'input_digests':digests,'response_id':response.get('id'),'usage':response.get('usage',{}),'wall_seconds':round(time.monotonic()-start,3),'failed_attempts':attempts}
  save(cache/(f'batch-{number:04d}.meta.json'),meta);return meta
 print(json.dumps({'provider':'DashScope text-embedding-v3','texts':len(records),'unique_texts':len(by_hash),'raw_chunks':len(raw),'pending_batches':len(batches)}),flush=True)
 with ThreadPoolExecutor(max_workers=4) as pool:
  for future in as_completed([pool.submit(run_batch,(offset+i+1,b)) for i,b in enumerate(batches)]):
   telemetry.append(future.result())
   if (len(telemetry)-previous_batches)%10==0 or len(telemetry)-previous_batches==len(batches):print(json.dumps({'finished_batches':len(telemetry)-previous_batches,'total_batches':len(batches),'wall_seconds':round(time.monotonic()-began,2)}),flush=True)
 all_vectors={}
 for name,rows in [('queries',queries),('descriptions',desc),('raw',raw)]:
  vectors=np.asarray([json.loads((cache/(text_keys[name,i]+'.json')).read_text())['embedding'] for i in range(len(rows))],dtype=np.float32)
  vectors/=np.linalg.norm(vectors,axis=1,keepdims=True);assert np.isfinite(vectors).all();all_vectors[name]=vectors
 np.savez_compressed(root/'embeddings.npz',**all_vectors,raw_case_indices=np.asarray([x['case_index'] for x in raw]),description_case_indices=np.asarray([x['case_index'] for x in desc]))
 metadata={'created_at_utc':datetime.now(timezone.utc).isoformat(),'model_source':amendment['embedding'],'runtime':{'numpy':np.__version__,'concurrent_requests':4,'max_rows_per_request':10},'encoding':{n:{'vectors':len(v),'truncated':0} for n,v in all_vectors.items()},'unique_texts':len(by_hash),'provider_batches':len(telemetry),'provider_input_tokens':sum(x['usage'].get('prompt_tokens',x['usage'].get('total_tokens',0)) for x in telemetry),'input_files':len(files),'input_bytes':sum(x['bytes'] for x in files),'excluded_files':len(excluded),'wall_seconds':round(time.monotonic()-began,3),'embeddings_sha256':sha(root/'embeddings.npz'),'telemetry':telemetry}
 save(root/'embedding-manifest.json',metadata);print(json.dumps({k:v for k,v in metadata.items() if k!='telemetry'},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
