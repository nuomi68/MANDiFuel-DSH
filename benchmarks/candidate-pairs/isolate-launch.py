#!/usr/bin/env python3
"""Apply a Linux Landlock allowlist to the entire DSH process and descendants.

This complements DSH workspace-write: filesystem reads cannot reach another arm,
organizer metadata, previous runs, or (for bare DSH) the plugin. Fail closed.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys

EXECUTE=1<<0
WRITE_FILE=1<<1
READ_FILE=1<<2
READ_DIR=1<<3
REFER=1<<13
TRUNCATE=1<<14
READ=EXECUTE|READ_FILE|READ_DIR
ALL=(1<<15)-1

class Ruleset(ctypes.Structure):
    _fields_=[('handled_access_fs',ctypes.c_uint64)]

class PathBeneath(ctypes.Structure):
    _pack_=1
    _fields_=[('allowed_access',ctypes.c_uint64),('parent_fd',ctypes.c_int32)]


def enforce(policy):
    libc=ctypes.CDLL(None,use_errno=True)
    abi=libc.syscall(444,0,0,1)
    if abi<3: raise RuntimeError(f'Landlock ABI >=3 required; found {abi}')
    attr=Ruleset(ALL)
    ruleset=libc.syscall(444,ctypes.byref(attr),ctypes.sizeof(attr),0)
    if ruleset<0: raise OSError(ctypes.get_errno(),'landlock_create_ruleset')
    try:
        for name in policy.get('listable',[]):
            descriptor=os.open(name,os.O_PATH|os.O_CLOEXEC)
            try:
                rule=PathBeneath(READ_DIR,descriptor)
                if libc.syscall(445,ruleset,1,ctypes.byref(rule),0)<0: raise OSError(ctypes.get_errno(),'landlock directory-listing rule')
            finally: os.close(descriptor)
        writable={str(Path(p).resolve()) for p in policy['writable']}
        readable={str(Path(p).resolve()) for p in policy['readable']}
        for name in sorted(readable|writable):
            path=Path(name)
            if not path.exists(): raise FileNotFoundError(name)
            access=ALL if name in writable else READ
            if not path.is_dir(): access &= EXECUTE|READ_FILE|WRITE_FILE|TRUNCATE
            descriptor=os.open(name,os.O_PATH|os.O_CLOEXEC)
            try:
                rule=PathBeneath(access,descriptor)
                if libc.syscall(445,ruleset,1,ctypes.byref(rule),0)<0:
                    raise OSError(ctypes.get_errno(),'landlock_add_rule: '+name)
            finally: os.close(descriptor)
        if libc.prctl(38,1,0,0,0)!=0: raise OSError(ctypes.get_errno(),'PR_SET_NO_NEW_PRIVS')
        if libc.syscall(446,ruleset,0)<0: raise OSError(ctypes.get_errno(),'landlock_restrict_self')
    finally: os.close(ruleset)
    return abi


def check(policy,abi):
    observations=[]
    for path in policy['denied_probe_files']:
        try:
            with open(path,'rb') as f: f.read(1)
            observations.append({'path':path,'denied':False})
        except PermissionError: observations.append({'path':path,'denied':True})
        except FileNotFoundError: observations.append({'path':path,'denied':False,'missing':True})
    for path in policy['allowed_probe_files']:
        try:
            with open(path,'rb') as f: f.read(1)
            observations.append({'path':path,'allowed':True})
        except OSError as exc: observations.append({'path':path,'allowed':False,'error':str(exc)})
    result={'landlock_abi':abi,'whole_process_and_descendants':True,'checks':observations,'passed':all(e.get('denied',e.get('allowed',False)) for e in observations)}
    Path(policy['check_output']).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    if not result['passed']: raise RuntimeError('isolation preflight failed')
    return result


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('policy',type=Path); parser.add_argument('--check-only',action='store_true'); parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args(); policy=json.loads(args.policy.read_text()); abi=enforce(policy); result=check(policy,abi)
    if args.check_only:
        print(json.dumps({'passed':result['passed'],'checks':len(result['checks']),'abi':abi})); return
    command=args.command
    if command and command[0]=='--': command=command[1:]
    if not command: parser.error('command required')
    os.execvpe(command[0],command,os.environ)


if __name__=='__main__': main()
