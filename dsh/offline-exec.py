#!/usr/bin/env python3
"""Task-only Landlock write boundary and seccomp offline execution; fail closed."""
from __future__ import annotations
import ctypes
import errno
import os
import platform
import sys
from pathlib import Path


class Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class PathBeneath(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def restrict_filesystem(project_root: str, runs_root: str | None = None) -> Path:
    root = Path(project_root).resolve(strict=True)
    if not root.is_dir() or root == Path('/'):
        raise RuntimeError("project root must be an existing directory other than /")
    writable = [root]
    if runs_root:
        runs = Path(runs_root)
        if runs != runs.resolve(strict=True) or not runs.is_dir() or root.is_relative_to(runs):
            raise RuntimeError("invalid canonical runs root")
        writable.append(runs)
    if not any(Path.cwd().is_relative_to(directory) for directory in writable):
        raise RuntimeError("task working directory is outside the project root")
    if sys.platform != 'linux' or platform.machine() not in {'x86_64', 'aarch64'}:
        raise RuntimeError("Linux Landlock is required for the project write boundary")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    abi = libc.syscall(444, None, 0, 1)
    # ABI 3 is mandatory: earlier kernels cannot restrict truncate(2).
    if abi < 3:
        raise RuntimeError("Landlock ABI >= 3 is required; refusing unconfined execution")
    handled = (1 << (16 if abi >= 5 else 15)) - 1
    ruleset = Ruleset(handled)
    fd = libc.syscall(444, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "Landlock ruleset creation failed")

    def allow(path: str, access: int) -> None:
        path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
        try:
            rule = PathBeneath(access, path_fd)
            if libc.syscall(445, fd, 1, ctypes.byref(rule), 0) != 0:
                raise OSError(ctypes.get_errno(), "Landlock path rule failed", path)
        finally:
            os.close(path_fd)

    try:
        allow('/', (1 << 0) | (1 << 2) | (1 << 3))  # read and execute dependencies
        for directory in writable:
            allow(str(directory), handled)
        allow('/dev/null', (1 << 1) | (1 << 2))  # shell redirection, no disk storage
        if libc.prctl(38, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS failed")
        if libc.syscall(446, fd, 0) != 0:
            raise OSError(ctypes.get_errno(), "Landlock enforcement failed")
    finally:
        os.close(fd)
    # Create only AFTER confinement, including when an ancestor was replaced by
    # a symlink. Neither shared /tmp nor a caller-controlled TMPDIR is granted.
    temporary = root / '.mandifuel-tmp'
    temporary.mkdir(mode=0o700, exist_ok=True)
    if not temporary.resolve(strict=True).is_relative_to(root):
        raise RuntimeError("project temporary directory escapes the project")
    for key in ('TMPDIR', 'TMP', 'TEMP'):
        os.environ[key] = str(temporary)
    os.environ['XDG_CACHE_HOME'] = str(root / '.mandifuel-cache')
    os.environ['MANDIFUEL_RAG_CACHE_DIR'] = str(root / '.mandifuel-cache' / 'rag')
    os.environ['MANDIFUEL_PROJECT_ROOT'] = str(root)
    return root


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
    project_root = os.environ.get('MANDIFUEL_PROJECT_ROOT')
    if args[:1] == ['--project-root'] and len(args) >= 2:
        project_root, args = args[1], args[2:]
    if not project_root:
        project_root = str(Path(__file__).resolve().parents[1])
    runs_root = None
    if args[:1] == ['--runs-root'] and len(args) >= 2:
        runs_root, args = args[1], args[2:]
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        print("usage: offline-exec.py -- command [args...]", file=sys.stderr)
        return 64
    try:
        restrict_filesystem(project_root, runs_root)
        deny_network()
        os.environ["MANDIFUEL_TASK_OFFLINE"] = "1"
        os.execvp(args[0], args)
    except (OSError, RuntimeError) as exc:
        print(f"MANDiFuel offline launcher: {exc}", file=sys.stderr)
        return 126


if __name__ == "__main__":
    raise SystemExit(main())
