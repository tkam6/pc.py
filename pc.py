#!/usr/bin/env -S python3 -BOO
import logging as lg
import os
import re
import shutil as sh
import subprocess as sp
import sys
import typing as ty

ANSI_RESET = "\x1b[0m"
ANSI_GREEN_4 = "\x1b[92m"
called_nm = os.path.basename(sys.argv[0])
lgr = lg.getLogger(__name__)
lg.basicConfig(
    format=f"{ANSI_GREEN_4}{called_nm}:{ANSI_RESET} %(message)s",
    level=lg.INFO
)


class Cfg(ty.NamedTuple):
    compiler: str | None
    no_docstrs: bool
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


def parse_args() -> Cfg:
    compiler = None
    no_docstrs = True
    lto = False
    keep_tmp = True
    rm_pyi = True
    quiet = True
    show_mods = False
    run = False
    mode = "standalone"
    onefile = False
    build_dir = None
    out_fl_nm = None
    args = []

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

        if tok in ("-h", "--help"):
            print("See the source, fuckass")
            sys.exit(1)
        if tok in ("-r", "--run"):
            run = True
        elif tok in ("-lto", "--enable-lto"):
            lto = True
        elif tok in ("-ds", "--docstrings"):
            no_docstrs = False
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
                sys.stderr.write(f"{called_nm}: Expected value for option '{tok}'\n")
                sys.exit(1)
            build_dir = toks[i + 1]
            skip = 1
        elif tok in ("-ofl", "--output-filename"):
            if i == len_toks - 1:
                sys.stderr.write(f"{called_nm}: Expected value for option '{tok}'\n")
                sys.exit(1)
            out_fl_nm = toks[i + 1]
            skip = 1
        elif tok in ("-sa", "--standalone"):
            mode = "standalone"
        elif tok in ("-of", "--onefile"):
            mode = "onefile"
        elif tok in "--clang":
            compiler = "clang"
        elif tok == "--":
            parse_opts_flags = False
        else:
            args.append(tok)

    min_num_args = 1
    max_num_args = 1
    if len(args) < min_num_args:
        sys.stderr.write(
            f"{called_nm}: Insufficient arguments; expected at least {min_num_args}, got {len(args)}\n"
        )
        sys.exit(2)
    elif len(args) > max_num_args:
        sys.stderr.write(
            f"{called_nm}: Unexpected arguments; expected at most {max_num_args}, got {len(args)}\n"
        )
        sys.exit(2)

    return Cfg(
        compiler=compiler,
        no_docstrs=no_docstrs,
        lto=lto,
        keep_tmp=keep_tmp,
        rm_pyi=rm_pyi,
        quiet=quiet,
        show_mods=show_mods,
        run=run,
        build_dir=build_dir,
        out_fl_nm=out_fl_nm,
        mode=mode,
        args=args
    )


def main() -> None:
    cfg = parse_args()

    usr_dir = os.path.expanduser("~")
    exec_pth = re.sub(f"^{usr_dir}", "~", sys.executable)
    lgr.info(f"Using binary {exec_pth}")
    fl = cfg.args[0]
    base_nm = os.path.splitext(os.path.basename(fl))[0]
    proj_root_dir = os.path.dirname(os.path.dirname(fl))
    build_dir = ("build" if cfg.build_dir is None else cfg.build_dir)
    out_fl_nm = (base_nm if cfg.out_fl_nm is None else cfg.out_fl_nm)
    build_dir_pth = os.path.join(proj_root_dir, build_dir)
    tmp_dir_pth = os.path.join(proj_root_dir, "tmp")
    py_dir_pth = os.path.join(proj_root_dir, "src", "py")
    cfg_fl_pth = os.path.join(proj_root_dir, "src", "cfg.py")

    cmd = [
        "python3",
        "-m",
        "nuitka",
        f"--mode={cfg.mode}",
        "--follow-imports",
        "--python-flag=no_docstrings" if cfg.no_docstrs else "",
        "--lto=yes" if cfg.lto else "--lto=no",
        # "--run" if cfg.run else "",
        f"--{cfg.compiler}" if cfg.compiler is not None else "",
        "--remove-output" if not cfg.keep_tmp else "",
        "--no-pyi-file" if cfg.rm_pyi else "",
        "--quiet" if cfg.quiet else "",
        "--show-modules" if cfg.show_mods else "",
        "--include-package=intrpr.builtin_cmds",
        f"--output-folder-name={build_dir}",
        f"--output-dir={proj_root_dir}",
        f"--output-filename={out_fl_nm}",
        "--no-deployment-flag=self-execution",
        cfg.args[0]
    ]

    sh.rmtree(build_dir_pth, ignore_errors=True)
    build_dir_prn = re.sub(f"^{usr_dir}", "~", os.path.abspath(build_dir_pth))
    lgr.info(f"Removed dir {build_dir_prn}")
    tmp_dir_prn = re.sub(f"^{usr_dir}", "~", os.path.abspath(tmp_dir_pth))
    sh.rmtree(tmp_dir_pth, ignore_errors=True)
    lgr.info(f"Removed dir {tmp_dir_prn}")
    compld_proc = sp.run(
        [i for i in cmd if i],
        text=True,
        capture_output=False
    )

    if compld_proc.returncode == 0:
        if cfg.keep_tmp:
            build_dot_build = os.path.join(proj_root_dir, "build.build")
            build_dot_build_prn = re.sub(
                f"^{usr_dir}",
                "~",
                os.path.abspath(build_dot_build)
            )
            sh.move(build_dot_build, tmp_dir_pth)
            lgr.info(f"Moved {build_dot_build_prn} to tmp")
        sh.move(
            os.path.join(proj_root_dir, build_dir + ".dist"),
            build_dir_pth
        )
        build_dot_dist = os.path.join(proj_root_dir, f"{build_dir}.dist")
        build_dot_dist_prn = re.sub(
            f"^{usr_dir}",
            "~",
            os.path.abspath(build_dot_dist)
        )
        lgr.info(f"Moved {build_dot_dist_prn} to {build_dir}")
        sh.copytree(py_dir_pth, os.path.join(build_dir_pth, "py"))
        lgr.info(f"Copied py to build directory")
        sh.copy2(cfg_fl_pth, build_dir_pth)
        lgr.info(f"Copied config to build directory")

        if cfg.run:
            op_xble = os.path.join(build_dir_pth, out_fl_nm)
            lgr.info(f"Running {op_xble}")
            sp.run([op_xble])

    else:
        lgr.error("Errors encountered")


if __name__ == "__main__":
    main()
