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
VALID_FLAGS = {
    "--",
    "-ds",  "--keep-docstrings",
    "-f",   "--force",
    "-h",   "--help",
    "-lto", "--enable-lto",
    "-nr",  "--no-rename",
    "-pyi", "--keep-pyi-file"
    "-Q",   "--quiet",
    "-r",   "--run",
    "-rtd", "--remove-tmp-dir",
    "-sm",  "--show-modules",
    "-sa",  "--standalone",
    "-of",  "--onefile",
    "-c",   "--clang",
}
VALID_OPTS = {
    "-bd",  "--build-dir",
    "-ofl", "--output-filename",
}
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
    EXPECTED_OPT_VAL = enum.auto()
    UNKNOWN_OPT_VAL = enum.auto()
    ARG_UNDERFLOW = enum.auto()
    ARG_OVERFLOW = enum.auto()
    BUILD_DIR_EXISTS = enum.auto()
    TMP_DIR_EXISTS = enum.auto()
    CANT_REMOVE_BUILD_DIR = enum.auto()
    SOME_FUCKING_ERR = enum.auto()


def debug(*msg: str) -> None:
    print(f"{ANSI_BOLD}D:{ANSI_RESET} {PROG}:", *msg, file=sys.stderr)

def info(*msg: str) -> None:
    print(f"{ANSI_BOLD}I:{ANSI_RESET} {PROG}:", *msg, file=sys.stderr)

def warn(*msg: str) -> None:
    print(
        f"{ANSI_BOLD}{ANSI_YELLOW_4}W:{ANSI_RESET} {PROG}:",
        *msg,
        file=sys.stderr
    )

def err(*msg: str) -> None:
    print(
        f"{ANSI_BOLD}{ANSI_RED_4}E:{ANSI_RESET} {PROG}:",
        *msg,
        file=sys.stderr
    )

def fatal(*msg: str, ret: int) -> ty.NoReturn:
    print(
        f"{ANSI_BOLD}{ANSI_RED_4}F:{ANSI_RESET} {PROG}:",
        *msg,
        file=sys.stderr
    )
    sys.exit(ret)


class Cfg(ty.NamedTuple):
    args        : list[str]
    build_dir   : str | None
    compiler    : str | None
    docstrs     : bool
    force       : bool
    keep_tmp    : bool
    lto         : bool
    mode        : str
    out_filename: str | None
    quiet       : bool
    remove_pyi  : bool
    rename      : bool
    run         : bool
    show_mods   : bool


def parse_args() -> Cfg:
    args         = []
    build_dir    = None
    compiler     = None
    docstrs      = False
    force        = False
    keep_tmp     = True
    lto          = False
    mode         = "standalone"
    out_filename = None
    quiet        = True
    remove_pyi   = True
    rename       = True
    run          = False
    show_mods    = False

    argv             = sys.argv[1:]
    len_argv         = len(argv)
    parse_opts_flags = True
    skip             = 0

    for i, param in enumerate(argv):
        if skip:
            skip -= 1
            continue
        if not param.startswith("-"):
            args.append(param)
            continue
        if not parse_opts_flags:
            args.append(param)
            continue
        if param not in (*VALID_OPTS, *VALID_FLAGS):
            err(f"unknown option/flag: {param}")
            sys.exit(RC.UNKNOWN_OPT_VAL)

        match param:
            # flags
            case "-h" | "--help":
                print("See the source, fuckass")
                sys.exit(1)
            case "-r" | "--run":
                run = True
            case "-f" | "--force":
                force = True
            case "-lto" | "--enable-lto":
                lto = True
            case "-ds" | "--keep-docstrings":
                docstrs = True
            case "-pyi" | "--keep-pyi-file":
                remove_pyi = False
            case "-rtd" | "--remove-tmp-dir":
                keep_tmp = False
            case "-Q" | "--no-quiet":
                quiet = False
            case "-sm" | "--show-modules":
                show_mods = True
            case "-sa" | "--standalone":
                mode = "standalone"
            case "-of" | "--onefile":
                mode = "onefile"
            case "-c" | "--clang":
                compiler = "clang"
            case "-nr" | "--no-rename":
                rename = False
            # options
            case "-bd" | "--build-dir":
                if i == len_argv - 1:
                    fatal(f"expected value: {param}", ret=RC.EXPECTED_OPT_VAL)
                build_dir = argv[i + 1]
                skip      = 1
            case "-ofl" | "--output-filename":
                if i == len_argv - 1:
                    fatal(f"expected value: '{param}'", ret=RC.EXPECTED_OPT_VAL)
                out_filename = argv[i + 1]
                skip         = 1
            # special
            case "--":
                parse_opts_flags = False
            case _:
                raise RuntimeError(
                    f"Should've never happened, but here we are. My dumbass forgot to include a case for an option/flag: {param}"
                )

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
        args=args,
        build_dir=build_dir,
        compiler=compiler,
        docstrs=docstrs,
        force=force,
        keep_tmp=keep_tmp,
        lto=lto,
        mode=mode,
        out_filename=out_filename,
        quiet=quiet,
        remove_pyi=remove_pyi,
        rename=rename,
        run=run,
        show_mods=show_mods,
    )


def condense_pth(pth: str) -> str:
    return re.sub(f"^{USR_DIR}", "~", pth)


def main() -> None:
    cfg = parse_args()
    cwd = os.getcwd()

    # not sys.executable as it'll point to current prog when compiled
    python_xble = sh.which("python3")
    if python_xble is None:
        fatal("cannot find Python", ret=RC.NO_PYTHON)
    python_xble_disp = condense_pth(python_xble)
    info(f"using binary {python_xble_disp}")

    file           = cfg.args[0]
    base_nm        = os.path.splitext(os.path.basename(file))[0]
    build_dir_nm   = ("build" if cfg.build_dir is None else cfg.build_dir)
    out_filename   = (base_nm if cfg.out_filename is None else cfg.out_filename)
    build_dir      = os.path.join(cwd, build_dir_nm)
    build_dir_disp = condense_pth(os.path.abspath(build_dir))
    tmp_dir        = os.path.join(cwd, "tmp")
    tmp_dir_disp   = condense_pth(os.path.abspath(tmp_dir))

    chk_nuitka = sp.run(
        [python_xble, "-m", "nuitka", "--help"],
        capture_output=True
    )
    if chk_nuitka.returncode != 0:
        fatal("cannot find Nuitka", ret=RC.NO_NUITKA)

    cmd = [
        python_xble,
        "-m",
        "nuitka",
        f"--mode={cfg.mode}",
        "--follow-imports",
        f"--output-folder-name={build_dir_nm}",
        f"--output-dir={cwd}",
        f"--output-filename={out_filename}",
        "--no-deployment-flag=self-execution",
        "--python-flag=no_docstrings" if not cfg.docstrs          else "",
        "--lto=yes"                   if cfg.lto                  else "--lto=no",
        f"--{cfg.compiler}"           if cfg.compiler is not None else "",
        "--remove-output"             if not cfg.keep_tmp         else "",
        "--no-pyi-file"               if cfg.remove_pyi           else "",
        "--quiet"                     if cfg.quiet                else "",
        "--show-modules"              if cfg.show_mods            else "",
        file,
    ]

    if os.path.isdir(build_dir) and not cfg.force:
        fatal(f"build directory already exists: {build_dir}", ret=RC.BUILD_DIR_EXISTS)
    if os.path.isdir(tmp_dir) and not cfg.force:
        fatal(f"tmp directory already exists: {tmp_dir}", ret=RC.TMP_DIR_EXISTS)

    # remove previous build directory
    try:
        sh.rmtree(build_dir)
    except FileNotFoundError:
        pass
    except sh.Error:
        fatal(f"cannot remove existing build dir {build_dir_disp}", ret=RC.CANT_REMOVE_BUILD_DIR)
    info(f"removed dir {build_dir_disp}")

    # remove previous tmp directory
    try:
        sh.rmtree(tmp_dir, ignore_errors=True)
    except FileNotFoundError:
        pass
    except sh.Error:
        err(f"cannot remove existing tmp dir {tmp_dir_disp}")
        sys.exit(3)
    info(f"removed dir {tmp_dir_disp}")

    # actually fucking run
    proc_done = sp.run([i for i in cmd if i])
    if proc_done.returncode != 0:
        fatal("errors encountered", ret=RC.SOME_FUCKING_ERR)

    # rename build.dist to build, build.build to tmp
    if cfg.rename:
        if cfg.keep_tmp:
            build_dot_build      = os.path.join(cwd, "build.build")
            build_dot_build_disp = condense_pth(os.path.abspath(build_dot_build))
            sh.move(build_dot_build, tmp_dir)
            info(f"moved {build_dot_build_disp} to tmp")
        build_dot_dist      = os.path.join(cwd, build_dir + ".dist")
        build_dot_dist_disp = condense_pth(os.path.abspath(build_dot_dist))
        sh.move(build_dot_dist, build_dir)
        info(f"moved {build_dot_dist_disp} to {build_dir}")

    # run output program
    if cfg.run:
        out_xble = os.path.join(build_dir, out_filename)
        info(f"running {out_xble}")
        sp.run([out_xble])


if __name__ == "__main__":
    main()
