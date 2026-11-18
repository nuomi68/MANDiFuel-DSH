#!/usr/bin/env python3
"""Verify saved OFFBEAT evidence without a browser, agent, or solver run."""
from argparse import ArgumentParser
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
from mandifuel_verify import verify_case


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--case',type=Path,required=True)
    parser.add_argument('--workspace',type=Path)
    parser.add_argument('--time',default='latest')
    parser.add_argument('--check',action='append',choices=['execution','heat','sphere','cesium'])
    parser.add_argument('--output',type=Path,help='Optional report outside the read-only case directory')
    args = parser.parse_args()
    if args.output and args.output.resolve().is_relative_to(args.case.resolve()): parser.error('核查输出必须放在原始算例目录之外')
    report = verify_case(args.case,workspace=args.workspace,time=args.time,checks=args.check)
    text = json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(text)
    else: print(text,end='')
    return 2 if report['state']=='stale' else 0


if __name__=='__main__': raise SystemExit(main())
