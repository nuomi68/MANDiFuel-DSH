#!/usr/bin/env python3
"""为任务子进程及其后代安装 Linux seccomp 离线过滤器，再执行原 argv。"""
from __future__ import annotations
import ctypes
import errno
import os
import platform
import sys


class Filter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint)]


class Program(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(Filter))]


def deny_network() -> None:
    # syscall numbers and audit architecture are kernel ABI, not Python versions.
    architecture = {
        "x86_64": (0xC000003E, 41, 425),
        "aarch64": (0xC00000B7, 198, 425),
    }.get(platform.machine())
    if sys.platform != "linux" or architecture is None:
        raise RuntimeError("unsupported Linux architecture; refusing to run without offline confinement")
    audit_arch, socket_nr, io_uring_setup_nr = architecture
    # Check architecture before syscall number. For x86-64, reject x32 ABI too.
    # Only Unix and netlink sockets are permitted. Internet, raw packet and
    # vsock creation return EPERM. io_uring_setup returns ENOSYS so libraries
    # use ordinary syscalls, which remain filtered. The filter survives exec
    # and is inherited by forked children; no_new_privs prevents privilege gain.
    rules = [
        Filter(0x20, 0, 0, 4),                 # LD seccomp_data.arch
        Filter(0x15, 1, 0, audit_arch),         # JEQ expected architecture
        Filter(0x06, 0, 0, 0x80000000),         # KILL_PROCESS otherwise
        Filter(0x20, 0, 0, 0),                 # LD syscall number
        Filter(0x35, 0, 1, 0x40000000),        # reject alternate ABI
        Filter(0x06, 0, 0, 0x00050000 | errno.ENOSYS),
        Filter(0x15, 0, 1, io_uring_setup_nr),
        Filter(0x06, 0, 0, 0x00050000 | errno.ENOSYS),
        Filter(0x15, 0, 4, socket_nr),
        Filter(0x20, 0, 0, 16),                # LD socket domain (arg0)
        Filter(0x15, 3, 0, 1),                 # AF_UNIX -> ALLOW
        Filter(0x15, 2, 0, 16),                # AF_NETLINK -> ALLOW
        Filter(0x06, 0, 0, 0x00050000 | errno.EPERM),
        Filter(0x06, 0, 0, 0x7FFF0000),         # other syscalls -> ALLOW
        Filter(0x06, 0, 0, 0x7FFF0000),
    ]
    array = (Filter * len(rules))(*rules)
    program = Program(len(rules), array)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                           ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(38, 1, 0, 0, 0) != 0:       # PR_SET_NO_NEW_PRIVS
        raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS failed")
    if libc.prctl(22, 2, ctypes.addressof(program), 0, 0) != 0:  # SECCOMP_MODE_FILTER
        raise OSError(ctypes.get_errno(), "seccomp offline filter failed")


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        print("usage: offline-exec.py -- command [args...]", file=sys.stderr)
        return 64
    try:
        deny_network()
        os.environ["MANDIFUEL_TASK_OFFLINE"] = "1"
        os.execvp(args[0], args)
    except (OSError, RuntimeError) as exc:
        print(f"MANDiFuel offline launcher: {exc}", file=sys.stderr)
        return 126


if __name__ == "__main__":
    raise SystemExit(main())
