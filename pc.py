#!/usr/bin/env -S python3 -BOO
# TODO: add a config file, which can include things like extra files that need
# to be copied into the build directory so that user willn't need to give those
# in command line every damn time
import enum
import logging as lg
import os
import pwd
import re
import shutil as sh
import subprocess as sp
import sys
import typing as ty

ANSI_RESET = "\x1b[0m"
ANSI_BOLD = "\x1b[1m"
ANSI_RED_4 = "\x1b[91m"
ANSI_GREEN_4 = "\x1b[92m"
ANSI_YELLOW_4 = "\x1b[93m"
MIN_ARGS = 1
MAX_ARGS = 1
VALID_OPTS = {}
VALID_FLAGS = {}
if not sys.argv:
    PROG = "[main]"
else:
    PROG = sys.argv[0]
    # Nuitka overwrites sys.argv[0]
    if "__compiled__" in locals():
        PROG = __compiled__.original_argv0
USR_DIR = pwd.getpwuid(os.getuid()).pw_dir
class RC(enum.IntEnum):
    ALL_GOOD = enum.auto(0)
    NO_PYTHON = enum.auto()
    NO_NUITKA = enum.auto()
    EXPD_OPT_VAL = enum.auto()
    ARG_UNDERFLOW = enum.auto()
    ARG_OVERFLOW = enum.auto()


def debug(*msg: str) -> None:
    print(f"{ANSI_BOLD}D:{ANSI_RESET} {PROG}:", *msg, file=sys.stderr)

def info(*msg: str) -> None:
    print(f"{ANSI_BOLD}I:{ANSI_RESET} {PROG}:", *msg, file=sys.stderr)

def warn(*msg: str) -> None:
    print(f"{ANSI_BOLD}{ANSI_YELLOW_4}W:{ANSI_RESET} {PROG}:", *msg, file=sys.stderr)

def err(*msg: str) -> None:
    print(f"{ANSI_BOLD}{ANSI_RED_4}E:{ANSI_RESET} {PROG}:", *msg, file=sys.stderr)

def fatal(*msg: str, ret: int) -> ty.NoReturn:
    print(f"{ANSI_BOLD}{ANSI_RED_4}F:{ANSI_RESET} {PROG}:", *msg, file=sys.stderr)
    sys.exit(ret)


class Cfg(ty.NamedTuple):
    compiler: str | None
    docstrs: bool
    lto: bool
    keep_tmp: bool
    rm_pyi: bool
    quiet: bool
    show_mods: bool
    run: bool
    build_dir: str | None
    out_fl_nm: str | None
    mode: str
    args: list[str]
    renm: bool


def parse_args() -> Cfg:
    # configuration flags
    compiler = None
    docstrs = False
    lto = False
    keep_tmp = True
    rm_pyi = True
    quiet = True
    show_mods = False
    run = False
    mode = "standalone"
    build_dir = None
    out_fl_nm = None
    args = []
    renm = True

    toks = sys.argv[1 :]
    len_toks = len(toks)
    parse_opts_flags = True
    skip = 0

    for i, tok in enumerate(toks):
        if skip:
            skip -= 1
            continue
        if not parse_opts_flags:
            args.append(tok)
            continue

        if tok in ("-h", "--help"):
            print("See the source, fuckass")
            sys.exit(1)
        if tok in ("-r", "--run"):
            run = True
        elif tok in ("-lto", "--enable-lto"):
            lto = True
        elif tok in ("-ds", "--docstrings"):
            docstrs = True
        elif tok in ("-pyi", "--pyi-file"):
            rm_pyi = False
        elif tok in ("-rtd", "--remove-tmp-dir"):
            keep_tmp = False
        elif tok in ("-Q", "--no-quiet"):
            quiet = False
        elif tok in ("-sm", "--show-modules"):
            show_mods = True
        elif tok in ("-bd", "--build-dir"):
            if i == len_toks - 1:
                fatal(f"expected value: {tok}", ret=RC.EXPD_OPT_VAL)
            build_dir = toks[i + 1]
            skip = 1
        elif tok in ("-ofl", "--output-filename"):
            if i == len_toks - 1:
                fatal(f"expected value: '{tok}'", ret=RC.EXPD_OPT_VAL)
            out_fl_nm = toks[i + 1]
            skip = 1
        elif tok in ("-sa", "--standalone"):
            mode = "standalone"
        elif tok in ("-of", "--onefile"):
            mode = "onefile"
        elif tok == "--clang":
            compiler = "clang"
        elif tok in ("-nr", "--no-rename"):
            renm = False
        elif tok == "--":
            parse_opts_flags = False
        else:
            args.append(tok)

    if len(args) < MIN_ARGS:
        fatal(
            f"argument underflow; {len(args)} not in [{MIN_ARGS}, {MAX_ARGS}]",
            ret=RC.ARG_UNDERFLOW,
        )
    elif len(args) > MAX_ARGS:
        fatal(
            f"argument overflow; {len(args)} not in [{MIN_ARGS}, {MAX_ARGS}]",
            ret=RC.ARG_OVERFLOW,
        )

    return Cfg(
        compiler=compiler,
        docstrs=docstrs,
        lto=lto,
        keep_tmp=keep_tmp,
        rm_pyi=rm_pyi,
        quiet=quiet,
        show_mods=show_mods,
        run=run,
        build_dir=build_dir,
        out_fl_nm=out_fl_nm,
        mode=mode,
        args=args,
        renm=renm,
    )


def condense_pth(pth: str) -> str:
    return re.sub(f"^{USR_DIR}", "~", pth)


def main() -> None:
    cfg = parse_args()

    cwd = os.getcwd()
    # sys.executable is not suitable as it'll point to current prog when compiled
    py_xbl = sh.which("python3")
    if py_xbl is None:
        fatal("cannot find Python", ret=RC.NO_PYTHON)
    py_xbl_disp = condense_pth(py_xbl)
    info(f"using binary {py_xbl_disp}")
    fl = cfg.args[0]
    base_nm = os.path.splitext(os.path.basename(fl))[0]
    build_dir_nm = ("build" if cfg.build_dir is None else cfg.build_dir)
    out_fl_nm = (base_nm if cfg.out_fl_nm is None else cfg.out_fl_nm)
    build_dir = os.path.join(cwd, build_dir_nm)
    build_dir_disp = condense_pth(os.path.abspath(build_dir))
    tmp_dir = os.path.join(cwd, "tmp")
    tmp_dir_disp = condense_pth(os.path.abspath(tmp_dir))

    chk_nuitka = sp.run([py_xbl, "-m", "nuitka", "--help"], capture_output=True)
    if chk_nuitka.returncode != 0:
        fatal("cannot find Nuitka", ret=RC.NO_NUITKA)

    cmd = [
        py_xbl,
        "-m",
        "nuitka",
        f"--mode={cfg.mode}",
        "--follow-imports",
        "--python-flag=no_docstrings" if not cfg.docstrs else "",
        "--lto=yes" if cfg.lto else "--lto=no",
        f"--{cfg.compiler}" if cfg.compiler is not None else "",
        "--remove-output" if not cfg.keep_tmp else "",
        "--no-pyi-file" if cfg.rm_pyi else "",
        "--quiet" if cfg.quiet else "",
        "--show-modules" if cfg.show_mods else "",
        f"--output-folder-name={build_dir_nm}",
        f"--output-dir={cwd}",
        f"--output-filename={out_fl_nm}",
        "--no-deployment-flag=self-execution",
        fl,
    ]

    # remove previous build and tmp directories
    try:
        sh.rmtree(build_dir)
    except FileNotFoundError:
        pass
    except sh.Error:
        err(f"cannot remove existing build dir {build_dir_disp}", ret=3)
    info(f"removed dir {build_dir_disp}")
    try:
        sh.rmtree(tmp_dir, ignore_errors=True)
    except FileNotFoundError:
        pass
    except sh.Error:
        err(f"cannot remove existing tmp dir {tmp_dir_disp}", ret=3)
    info(f"removed dir {tmp_dir_disp}")

    # actually run
    compld_proc = sp.run([i for i in cmd if i])
    if compld_proc.returncode != 0:
        err("errors encountered")
        sys.exit(1)

    # rename build.dist to build, build.build to tmp
    if cfg.renm:
        if cfg.keep_tmp:
            build_dot_build = os.path.join(cwd, "build.build")
            build_dot_build_disp = condense_pth(os.path.abspath(build_dot_build))
            sh.move(build_dot_build, tmp_dir)
            info(f"moved {build_dot_build_disp} to tmp")
        build_dot_dist = os.path.join(cwd, build_dir + ".dist")
        build_dot_dist_disp = condense_pth(os.path.abspath(build_dot_dist))
        sh.move(build_dot_dist, build_dir)
        info(f"moved {build_dot_dist_disp} to {build_dir}")

    # run output program
    if cfg.run:
        op_xble = os.path.join(build_dir, out_fl_nm)
        info(f"running {op_xble}")
        sp.run([op_xble])


if __name__ == "__main__":
    main()
