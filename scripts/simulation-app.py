#!/usr/bin/env python3
"""Backend agent and terminal entry point to the same persistent calculator as the Web UI."""
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
from mandifuel_app.runtime import Application


def main():
    parser = argparse.ArgumentParser(description='从已完成的 OFFBEAT 算例生成、演化和执行计算器')
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('--case', required=True, help='算例目录，相对于任务工作区')
    parser.add_argument('--store', type=Path, help='独立应用存储；默认与工作台共享任务的 applications 目录')
    sub = parser.add_subparsers(dest='action',required=True)
    sub.add_parser('inspect')
    candidate = sub.add_parser('candidate')
    candidate.add_argument('--candidate-case',required=True)
    create = sub.add_parser('create')
    create.add_argument('--definition',type=Path,required=True)
    evolution = sub.add_parser('evolve')
    evolution.add_argument('--version',type=int,required=True)
    evolution.add_argument('--definition',type=Path,required=True)
    run = sub.add_parser('run')
    run.add_argument('--version',type=int,required=True)
    run.add_argument('--values',required=True, help='参数 ID 与数值组成的 JSON 对象')
    run.add_argument('--candidate-case',help='可选，按候选输入卡再次核对全部可执行参数')
    run.add_argument('--request-id',help='重试时传回同一个 32 位十六进制请求标识')
    opt = parser.parse_args()
    workspace = opt.workspace.resolve()
    store = opt.store or (workspace.parent/'applications' if (workspace.parent/'task.json').is_file()
                          else workspace/'.mandifuel-apps')
    app = Application(workspace,opt.case,store)
    if opt.action=='create':
        if os.environ.get('DSH_MANDIFUEL_WEB_CALCULATOR')=='switch':
            raise ValueError('请在已完成工况中打开「生成计算器」开关，由专用构建会话生成。')
        response = app.create(json.loads(opt.definition.read_text()))
    elif opt.action=='inspect':
        if app.spec.is_file():
            response = app.state()
        else:
            try: response = app.capabilities()
            except (ValueError,OSError) as error: response = dict(available=False,reason=str(error))
    elif opt.action=='candidate':
        response = app.candidate(opt.candidate_case)
    elif opt.action=='evolve':
        response = app.evolve(opt.version,proposal=json.loads(opt.definition.read_text()))
    else:
        response = app.run(opt.version,opt.request_id or uuid4().hex,json.loads(opt.values),opt.candidate_case)
    print(json.dumps(response,ensure_ascii=False,indent=2))
    return 1 if response.get('status')=='failed' else 0


if __name__=='__main__':
    try:
        sys.exit(main())
    except (ValueError,OSError) as error:
        sys.exit(str(error))
