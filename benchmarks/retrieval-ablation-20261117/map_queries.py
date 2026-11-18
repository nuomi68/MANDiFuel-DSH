"""Map queries through native DSH, with qrels/corpus inaccessible to the process."""
import argparse,hashlib,json,os,shutil,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path

HERE=Path(__file__).resolve().parent;REPO=HERE.parent.parent
NODE='/home/lwz/.nvm/versions/node/v22.23.2/bin/node'
DSH='/home/lwz/.nvm/versions/node/v22.23.2/lib/node_modules/@deepseek-ai/dsh/lib/bin.js'
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def extract(folder):
 final=[];usage={};calls=0;requests=0;routes=[]
 for p in sorted((folder/'traces').rglob('session.jsonl')):
  for line in p.read_text().splitlines():
   e=json.loads(line);d=e.get('data',{});kind=e.get('type')
   if kind=='tool/call':calls+=1
   if kind=='assistant/message':
    requests+=1
    for k,v in d.get('usage',{}).items():
     if isinstance(v,(int,float)):usage[k]=usage.get(k,0)+v
    m=d.get('message',{});route=m.get('source',{})
    if route.get('provider'):routes.append({k:route[k] for k in ['provider','model'] if k in route})
    for b in m.get('content',[]):
     if b.get('type')=='text':final.append(b.get('text',''))
 raw='\n'.join(final).strip()
 if raw.startswith('```'):raw=raw.split('\n',1)[1].rsplit('```',1)[0].strip()
 # Accept only a JSON response, no recovery using gold or retrieval outcomes.
 result=json.loads(raw)
 return result,{'tool_calls':calls,'assistant_messages':requests,'tokens':usage,'routes':routes}

def main():
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args();root=args.root.resolve()
 sys.path.insert(0,str(root/'frozen'));import query as rq
 queries=json.loads((root/'frozen/queries.json').read_text());vocab=json.loads((root/'frozen/vocabulary.json').read_text())
 out=root/'mapping';out.mkdir(exist_ok=True)
 private=Path('/tmp')/('mandifuel-retrieval-mapper-'+hashlib.sha256(str(root).encode()).hexdigest()[:10]);private.mkdir(mode=0o700,exist_ok=True)
 batches=[]
 for i in range(0,len(queries),8):
  ident=f'batch-{i//8+1:02d}';folder=out/ident;folder.mkdir(exist_ok=True)
  for name in ['runtime','workspace','traces','tmp']:(folder/name).mkdir(exist_ok=True)
  home=private/ident;home.mkdir(mode=0o700,exist_ok=True)
  if not (home/'profiles').exists():
   (home/'profiles').mkdir();shutil.copytree('/home/lwz/.dsh/profiles/headless',home/'profiles/headless',symlinks=True)
   (home/'profiles/node_modules').symlink_to('/home/lwz/.dsh/profiles/node_modules',target_is_directory=True)
  for name in ['settings.yaml','.credentials.yaml','.anonymous-user-id','cordis.patch.yml']:
   src=Path('/home/lwz/.dsh')/name
   if src.is_file():shutil.copyfile(src,home/name);(home/name).chmod(0o600)
  prompt='Map each query independently. Do not infer labels from other questions. Return ONLY {"mappings": [{"id": query id, "mapping": the schema below}, ...]}. No tools, explanations or filesystem access. Include all eight IDs exactly once.\nSchema:\n'+json.dumps(rq._mapping_schema(vocab['facets']))+'\nAllowed vocabulary:\n'+json.dumps(vocab['labels'],ensure_ascii=False)+'\nQueries:\n'+json.dumps([{'id':q['id'],'text':q['text']} for q in queries[i:i+8]],ensure_ascii=False)
  (folder/'runtime/prompt.txt').write_text(prompt)
  patch='- id: system-prompt\n  config:\n    persona: '+json.dumps(rq.SYSTEM_PROMPT)+'\n- id: agent-default-model\n  config:\n    provider: deepseek-official\n    model: deepseek-v4-flash\n    reasoningEffort: high\n- id: session-persistence-jsonl\n  config:\n    root: !!js process.env.BENCH_TRACE_ROOT\n    compression: none\n    packChunks: false\n'
  base=Path('/home/lwz/.dsh/profiles/node_modules/@deepseek-ai/dsh-base/cordis.patch.yml').read_text()
  import re
  disabled=[x for x in re.findall(r'^    - id: (\S+)',base,re.M) if x.startswith(('tool-','web-search','web-fetch'))]
  disabled+=['skill-filesystem','agent-instructions','session-title-llm','session-telemetry-otel']
  for name in sorted(set(disabled)):patch+=f'- id: {name}\n  disabled: true\n'
  (folder/'runtime/mapping.patch.yml').write_text(patch)
  shutil.copyfile(REPO/'benchmarks/candidate-pairs/isolate-launch.py',folder/'runtime/isolate-launch.py')
  policy={'listable':['/'],'readable':[s for s in ['/usr','/bin','/lib','/lib64','/etc','/etc/resolv.conf','/proc','/dev','/sys','/opt','/home/lwz/.nvm/versions/node/v22.23.2','/home/lwz/.dsh/profiles',str(folder/'runtime')] if Path(s).exists()], 'writable':[str(folder/n) for n in ['workspace','traces','tmp']]+[str(home),'/dev/null','/dev/tty'],'denied_probe_files':[str(root/'frozen/qrels.json'),str(root/'frozen/corpus.json'),str(root/'frozen/tasks.json')],'allowed_probe_files':[str(folder/'runtime/prompt.txt')],'check_output':str(folder/'workspace/isolation-check.json')}
  save(folder/'runtime/isolation.json',policy)
  batches.append((folder,home,prompt,queries[i:i+8]))
 def run(item):
  folder,home,prompt,subset=item
  if (folder/'mappings.json').exists():return json.loads((folder/'mappings.json').read_text())
  env=dict(os.environ,DSH_HOME=str(home),TMPDIR=str(folder/'tmp'),BENCH_TRACE_ROOT=str(folder/'traces'),DSH_TELEMETRY_DISABLED='1',PYTHONDONTWRITEBYTECODE='1')
  cmd=[sys.executable,'-B',str(folder/'runtime/isolate-launch.py'),str(folder/'runtime/isolation.json'),'--',NODE,DSH,'--profile','headless','--patch',str(folder/'runtime/mapping.patch.yml'),prompt]
  began=time.monotonic()
  with (folder/'stdout.log').open('w') as stdout,(folder/'stderr.log').open('w') as stderr:
   proc=subprocess.run(cmd,cwd=folder/'workspace',env=env,stdout=stdout,stderr=stderr,timeout=600)
  meta={'exit_code':proc.returncode,'wall_seconds':round(time.monotonic()-began,3)}
  if proc.returncode:save(folder/'run.json',meta);raise RuntimeError(folder.name+' failed; inspect stderr')
  result,trace=extract(folder);meta.update(trace);save(folder/'run.json',meta)
  assert trace['tool_calls']==0
  assert sorted(x['id'] for x in result['mappings'])==sorted(q['id'] for q in subset)
  source={q['id']:q for q in subset};validated={}
  for x in result['mappings']:validated[x['id']]=rq._validate_mapping(x['mapping'],source[x['id']]['text'],vocab['labels'],vocab['facets'])
  save(folder/'mappings.json',validated)
  print(json.dumps({'batch':folder.name,**meta}),flush=True)
  return validated
 merged={}
 with ThreadPoolExecutor(max_workers=4) as pool:
  for f in as_completed([pool.submit(run,b) for b in batches]):merged.update(f.result())
 assert set(merged)=={q['id'] for q in queries}
 save(out/'mappings.json',merged)
 print(json.dumps({'mapped_queries':len(merged),'tools':0,'qrels_inaccessible':True}),flush=True)

if __name__=='__main__':main()
