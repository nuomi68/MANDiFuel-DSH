#!/usr/bin/env python3
"""OFFBEAT workbench mounted inside the native DeepSeek Harness Web host."""
from argparse import ArgumentParser
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote,urlsplit,parse_qs,quote
import json
import os
import secrets
import signal
import socket
import re
import subprocess
import threading
from registry import TaskRegistry,REPO
from slot_protocol import FrontendConflict

ROOT=Path(__file__).resolve().parent
TOKEN=secrets.token_urlsafe(32)


def presenter_directory(runtime,project):
    # Historical runs can be mounted outside the solver's write boundary.
    # The private UI operator needs only its own empty, project-local cwd.
    workspace=runtime/'presenter-workspace'
    if not workspace.resolve().is_relative_to(project.resolve()):
        workspace=project/'.mandifuel-tmp'/'presenter-workspace'
    if not workspace.resolve().is_relative_to(project.resolve()):
        raise ValueError('前端操作工作目录须位于项目内')
    workspace.mkdir(parents=True,exist_ok=True)
    return workspace.resolve()


class Handler(SimpleHTTPRequestHandler):
    def send_json(self,value,status=200,head=False):
        body=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
        try:
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers()
            if not head:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
            self.close_connection=True
    def end_headers(self):
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        super().end_headers()
    def local_request(self):
        host=self.headers.get('Host','');origin=self.headers.get('Origin');site=self.headers.get('Sec-Fetch-Site','')
        return urlsplit('//'+host).hostname in {'127.0.0.1','localhost','::1'} and (not origin or urlsplit(origin).netloc==host) and site!='cross-site'
    def serve(self,head=False):
        parsed=urlsplit(self.path);path=unquote(parsed.path);manager=self.server.manager
        if path.startswith('/api/'):
            if not self.local_request():return self.send_json({'error':'仅支持本地同源访问'},403,head=head)
            try:
                if path=='/api/tasks':
                    return self.send_json(manager.list(),head=head)
                if path=='/api/runtime':return self.send_json({'enabled':True,'native':True,'protocol':7,'token':TOKEN},head=head)
                if path=='/api/health':return self.send_json({'status':'ok','mode':'native-harness-workbench','protocol':7,'tasks':sum(not t['draft'] for t in manager.list()),'observer':manager.dashboard.health()},head=head)
                parts=path.strip('/').split('/')
                if len(parts)>=3 and parts[1]=='tasks':
                    ident=parts[2];resource=parts[3] if len(parts)==4 else None
                    if len(parts)==3:return self.send_json(manager.snapshot(ident),head=head)
                    if resource=='calculator':
                        from calculator_api import get
                        return self.send_json(get(manager,ident,parse_qs(parsed.query)),head=head)
                    if resource=='fields':return self.send_json(manager.fields(ident,parse_qs(parsed.query).get('view',[None])[0]),head=head)
                    if resource=='study':return self.send_json(manager.study(ident),head=head)
                    if resource=='observe':return self.send_json(manager.dashboard.inspect(ident),head=head)
                    if resource=='evidence':
                        query=parse_qs(parsed.query)
                        return self.send_json(manager.evidence.index(ident,query.get('claim',[None])[0],query.get('source',[None])[0]),head=head)
                    if resource=='frontend':
                        from frontend_session import snapshot
                        query=parse_qs(parsed.query)
                        return self.send_json(snapshot(manager.dashboard,ident,query.get('target',['page'])[0],query.get('node',[None])[0]),head=head)
                    if resource=='ui-data':
                        query=parse_qs(parsed.query);revision=int(query['revision'][0]) if 'revision' in query else None
                        return self.send_json(manager.dashboard.ui_dataset(ident,query.get('dataset',[''])[0],revision),head=head)
                    if resource=='ui-image':
                        p=manager.dashboard.ui_image(ident,parse_qs(parsed.query).get('file',[''])[0]);body=p.read_bytes();self.send_response(200);self.send_header('Content-Type',{'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}[p.suffix.lower()]);self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers()
                        if not head:self.wfile.write(body)
                        return
                    if resource=='progress':return self.send_json(manager.progress(ident),head=head)
                    if resource=='events':return self.send_json(manager.events(ident),head=head)
                    if resource=='stream' and not head:return self.stream(ident)
                    if resource=='file':
                        p=manager.file(ident,parse_qs(parsed.query).get('path',[''])[0]);body=p.read_bytes();self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(p.name));self.send_header('Content-Length',str(len(body)));self.end_headers()
                        if not head:self.wfile.write(body)
                        return
                return self.send_json({'error':'未找到资源'},404,head=head)
            except KeyError:return self.send_json({'error':'任务不存在'},404,head=head)
            except (ValueError,OSError) as e:return self.send_json({'error':str(e)},400,head=head)
        target=(ROOT/path.lstrip('/')).resolve()
        if not target.is_relative_to(ROOT) or path!='/' and not path.startswith('/assets/') or target.is_dir() and path!='/':return self.send_error(404)
        if head:super().do_HEAD()
        else:super().do_GET()
    def do_GET(self):self.serve()
    def do_HEAD(self):self.serve(head=True)
    def do_POST(self):
        if not self.local_request() or not secrets.compare_digest(self.headers.get('X-Workbench-Token',''),TOKEN):return self.send_json({'error':'本地会话校验失败，请刷新页面'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=262144:raise ValueError('请求大小无效')
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):raise ValueError('请求必须是 JSON 对象')
            path=urlsplit(self.path).path;parts=path.strip('/').split('/');manager=self.server.manager
            if path=='/api/process-briefs':
                from process_briefs import pending
                return self.send_json(pending(manager))
            if path=='/api/draft':return self.send_json(manager.draft())
            if path=='/api/adopt':return self.send_json(manager.adopt(str(data['cwd']),str(data['sessionId'])))
            if path=='/api/tasks':return self.send_json(manager.prepare(str(data.get('prompt','')),str(data.get('title','')),data.get('source')),201)
            if len(parts)==4 and parts[:2]==['api','tasks']:
                if parts[3]=='process-summary':
                    from process_briefs import publish
                    return self.send_json(publish(manager,parts[2],data))
                if parts[3]=='calculator-build-state':
                    from calculator_api import build
                    return self.send_json(build(manager,parts[2],data))
                if parts[3]=='calculator':
                    from calculator_api import post
                    return self.send_json(post(manager,parts[2],data))
                if parts[3] in {'selection-check','selection-check-result'}:
                    from frontend_session import selection_check,selection_check_result
                    operation=selection_check if parts[3]=='selection-check' else selection_check_result
                    return self.send_json(operation(manager,parts[2],data))
                if parts[3]=='present':return self.send_json(manager.dashboard.publish(parts[2],data))
                if parts[3]=='frontend':
                    from frontend_session import apply
                    return self.send_json(apply(manager.dashboard,parts[2],data))
                if parts[3]=='parameter-values':return self.send_json(manager.dashboard.parameter_values(parts[2],data))
                if parts[3]=='viewer-state':return self.send_json(manager.dashboard.viewer_state(parts[2],data))
                if parts[3]=='ui-state':return self.send_json(manager.dashboard.ui_state(parts[2],data))
                if parts[3]=='presenter':
                    return self.send_json({'updated':manager.set_presenter(parts[2],data)})
                if parts[3]=='bind':return self.send_json(manager.bind(parts[2],str(data['sessionId']),data.get('workspaceId')))
                if parts[3]=='native-event':return self.send_json(manager.native_event(parts[2],data))
            return self.send_json({'error':'未找到资源'},404)
        except FrontendConflict as error:return self.send_json({'error':str(error),'code':'stale_frontend'},409)
        except KeyError:return self.send_json({'error':'任务不存在'},404)
        except (ValueError,OSError) as error:return self.send_json({'error':str(error)},400)
    def stream(self,ident):
        manager=self.server.manager;snapshot=manager.snapshot(ident);cursor=snapshot['cursor'];self.send_response(200);self.send_header('Content-Type','text/event-stream; charset=utf-8');self.send_header('X-Accel-Buffering','no');self.end_headers()
        def send(event,payload,ident=None):
            text=(f'id: {ident}\n' if ident is not None else '')+'event: '+event+'\ndata: '+json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n\n';self.wfile.write(text.encode());self.wfile.flush()
        try:
            send('snapshot',snapshot,cursor)
            while not manager.shutting_down:
                updates=manager.updates(ident,cursor)
                if not updates:self.wfile.write(b': keepalive\n\n');self.wfile.flush()
                for update in updates:cursor=update['id'];send(update['kind'],update['data'],cursor)
        except (BrokenPipeError,ConnectionResetError,OSError):pass


def main():
    parser=ArgumentParser(description='OFFBEAT 工作台 + 原生 DeepSeek Harness Web')
    parser.add_argument('--host',default='127.0.0.1',choices=['127.0.0.1']);parser.add_argument('--port',type=int,default=18765);parser.add_argument('--data-dir',type=Path);parser.add_argument('--no-presenter',action='store_true',help='仅用于离线界面验收，不启动展示模型')
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error('端口必须在 1–65535 之间')
    # Check before opening task storage or launching the native host.
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            probe.bind((args.host,args.port))
    except OSError as error:
        parser.exit(1,f'工作台无法启动：端口 {args.port} 不可用（{error.strerror}）。\n请在旧服务的终端按 Ctrl+C 结束旧实例后重试，或使用 --port 指定其他端口。\n')
    manager=TaskRegistry(args.data_dir)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)));server.manager=manager
    threading.Thread(target=server.serve_forever,daemon=True).start()
    runtime=manager.root/'native-host';runtime.mkdir(exist_ok=True);patch=runtime/'workbench.patch.yml'
    patch.write_text('- insert:\n    - id: mandifuel-native-workbench\n      name: '+json.dumps(str(ROOT/'native-plugin/index.mjs'))+'\n')
    presenter_work=presenter_directory(runtime,REPO)
    env=dict(os.environ,MANDIFUEL_PRESENTATION_ENABLED='0' if args.no_presenter else '1',MANDIFUEL_PRESENTER_WORKSPACE=str(presenter_work),MANDIFUEL_WORKBENCH_BACKEND=f'http://127.0.0.1:{server.server_port}',MANDIFUEL_WORKBENCH_TOKEN=TOKEN)
    process=None
    def terminate(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,terminate)
    signal.signal(signal.SIGHUP,terminate)
    try:
        process=subprocess.Popen(['bash',str(REPO/'scripts/start-dsh.sh'),'web','--patch',str(patch),'--no-open','--port',str(args.port)],cwd=REPO,env=env,stdout=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',start_new_session=True)
        for line in process.stdout:
            match=re.search(r'dsh web:\s*(https?://\S+)',line)
            if match:
                url=urlsplit(match.group(1));print('OFFBEAT 工作台: '+url._replace(path='/workbench/').geturl(),flush=True)
            else:print(line,end='',flush=True)
        code=process.wait()
        if code:raise SystemExit(code)
    except KeyboardInterrupt:pass
    finally:
        # The launcher may have exited while its native child still owns the port.
        if process:
            try:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=15)
            except ProcessLookupError:pass
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
        manager.close();server.shutdown();server.server_close()

if __name__=='__main__':main()
