#!/usr/bin/env -S python3 -BOO
import dataclasses as dcs
import enum
import os
import pwd
import re
import shutil as sh
import subprocess as sp
import sys
import tomllib as tl
import typing as ty


###############################################################################
### CONSTANTS AND ERROR CODES
###############################################################################

ANSI_RESET    = "\x1b[0m"
ANSI_BOLD     = "\x1b[1m"
ANSI_RED_4    = "\x1b[91m"
ANSI_GREEN_4  = "\x1b[92m"
ANSI_YELLOW_4 = "\x1b[93m"

MIN_ARGS = 0
MAX_ARGS = 1

VALID_FLAGS = {
    "--",
    "--standalone",
    "--onefile",
    "--clang",
    "-d", "--keep-docstrings",
    "-f", "--force",
    "-h", "--help",
    "-l", "--enable-lto",
    "-m", "--show-modules",
    "-p", "--keep-pyi-file",
    "-q", "--no-quiet",
    "-R", "--no-rename",
    "-r", "--run",
    "-T", "--remove-tmp-dir",
    "-u", "--dry-run",
}
VALID_OPTS = {
    "-b", "--build-dir",
    "-i", "--data-dir",
    "-n", "--output-filename",
}
VALID_TOML_BOOL_KEYS = {
    "force"          : "force",
    "keep-pyi-file"  : "pyi",
    "keep-tmp-dir"   : "keep_tmp",
    "keep-docstrings": "docstrs",
    "lto"            : "lto",
    "quiet"          : "quiet",
    "run"            : "run",
    "rename"         : "rename",
    "show-modules"   : "show_mods",
}
VALID_TOML_STR_KEYS = {
    "build-directory": "build_dir",
    "data-directory" : "data_dir",
    "output-filename": "out_filename",
    "file"           : "file",
}
if not sys.argv:
    PROG = "[main]"
else:
    PROG = sys.argv[0]
    # Nuitka overwrites sys.argv[0]
    if "__compiled__" in locals():
        PROG = __compiled__.original_argv0
USER_DIR = pwd.getpwuid(os.getuid()).pw_dir


class RC(enum.IntEnum):
    ALL_GOOD              = enum.auto(0)
    NO_PYTHON             = enum.auto()
    NO_NUITKA             = enum.auto()
    EXPECTED_OPT_VAL      = enum.auto()
    UNKNOWN_OPT_VAL       = enum.auto()
    ARG_UNDERFLOW         = enum.auto()
    ARG_OVERFLOW          = enum.auto()
    BUILD_DIR_EXISTS      = enum.auto()
    TMP_DIR_EXISTS        = enum.auto()
    CANT_REMOVE_BUILD_DIR = enum.auto()
    CANT_TMP_BUILD_DIR    = enum.auto()
    SOME_FUCKING_ERR      = enum.auto()
    FILE_404              = enum.auto()
    DIR_404               = enum.auto()
    IS_A_DIR              = enum.auto()
    ACCESS_DENIED         = enum.auto()
    OS_ERR                = enum.auto()
    TOML_DECODE_ERR       = enum.auto()
    TOML_INV_TYPE         = enum.auto()
    NO_INPUT_FILE         = enum.auto()


###############################################################################
### GENERAL
###############################################################################

@dcs.dataclass
class Config:
    args        : list[str]  = dcs.field(default_factory=list)
    build_dir   : str | None = None
    compiler    : str | None = None
    data_dirs   : list[str]  = dcs.field(default_factory=list)
    docstrs     : bool       = False
    dry_run     : bool       = False
    force       : bool       = False
    keep_tmp    : bool       = True
    lto         : bool       = False
    mode        : str        = "standalone"
    out_filename: str | None = None
    quiet       : bool       = False
    pyi         : bool       = False
    rename      : bool       = True
    run         : bool       = False
    show_mods   : bool       = False
    file        : str | None = None


def condense_path(path: str) -> str:
    return re.sub(f"^{USER_DIR}", "~", path)


def pretty_prn_list_of_str(
    l          : list[str],
    indent     : int = 0,
    indent_size: int = 4
) -> None:
    indent_block = indent_size * " "
    print(indent * indent_block + "[")
    for s in l:
        print((indent + 1) * indent_block + repr(s), end=",\n")
    print(indent * indent_block + "]")


###############################################################################
### LOGGING
###############################################################################

def debug(*msg: str) -> None:
    print(f"{ANSI_BOLD}D:{ANSI_RESET}", *msg, file=sys.stderr)

def info(*msg: str) -> None:
    print(f"{ANSI_BOLD}I:{ANSI_RESET}", *msg, file=sys.stderr)

def warn(*msg: str) -> None:
    print(f"{ANSI_BOLD}{ANSI_YELLOW_4}W:{ANSI_RESET}", *msg, file=sys.stderr)

def err(*msg: str) -> None:
    print(f"{ANSI_BOLD}{ANSI_RED_4}E:{ANSI_RESET}", *msg, file=sys.stderr)

def fatal(*msg: str, ret: int) -> ty.NoReturn:
    print(f"{ANSI_BOLD}{ANSI_RED_4}F:{ANSI_RESET}", *msg, file=sys.stderr)
    sys.exit(ret)


###############################################################################
### CONFIG FILE
###############################################################################

def read_toml_file(filepath: str) -> dict[str, ty.Any] | ty.NoReturn:
    try:
        return tl.load(open(filepath, "rb"))
    except FileNotFoundError as e:
        pass
    except PermissionError as e:
        fatal(f"access denied: {filepath}", ret=RC.ACCESS_DENIED)
    except IsADirectoryError as e:
        fatal(f"is a directory: {filepath}", ret=RC.IS_A_DIR)
    except OSError as e:
        fatal(f"OS error; {e.strerror}", ret=RC.OS_ERR)
    except tl.TOMLDecodeError as e:
        fatal(f"cannot read TOML: {filepath}", ret=RC.TOML_DECODE_ERR)
    return {}


def get_config_from_toml(
        config_obj: "Config",
        toml_data: dict[str, ty.Any]
    ) -> "Config" | ty.NoReturn:
    for key, value in toml_data.items():
        if key in VALID_TOML_BOOL_KEYS and not isinstance(value, bool):
            fatal(
                f"expected bool for key {key} in config file, got {value.__class__.__name__}",
                ret=RC.TOML_INV_TYPE,
            )
        elif key in VALID_TOML_STR_KEYS and not isinstance(value, str):
            fatal(
                f"expected str for key {key} in config file, got {value.__class__.__name__}",
                ret=RC.TOML_INV_TYPE,
            )
        if key in ("standalone", "onefile"):
            config_obj.mode = key
        elif key == "clang":
            config_obj.compiler = "clang"
        elif key in VALID_TOML_BOOL_KEYS:
            setattr(config_obj, VALID_TOML_BOOL_KEYS[key], value)
        elif key in VALID_TOML_STR_KEYS:
            setattr(config_obj, VALID_TOML_STR_KEYS[key], value)

    return config_obj


###############################################################################
### ARGV PARSING
###############################################################################

def parse_args(config_obj: Config) -> Config:
    argv             = sys.argv[1:]
    parse_opts_flags = True
    len_argv         = len(argv)
    i                = 0

    while i < len(argv):
        param = argv[i]
        if not parse_opts_flags:
            config_obj.args.append(param)
            i += 1
            continue
        if not param.startswith("-"):
            config_obj.args.append(param)
            i += 1
            continue
        if param not in (*VALID_OPTS, *VALID_FLAGS):
            for ch in param[1 :]:
                if f"-{ch}" not in VALID_FLAGS:
                    fatal(f"unknown option/flag: {param}", ret=RC.UNKNOWN_OPT_VAL)
            argv[i : i + 1] = [f"-{c}" for c in param[1 :]]
            continue
        if param in VALID_OPTS and i >= len(argv) - 1:
            fatal(f"expected value: '{param}'", ret=RC.EXPECTED_OPT_VAL)

        match param:
            # flags
            case "-h" | "--help":
                print("See the source, fuckass")
                sys.exit(1)
            case "-r" | "--run":
                config_obj.run = True
            case "-f" | "--force":
                config_obj.force = True
            case "-l" | "--enable-lto":
                config_obj.lto = True
            case "-d" | "--keep-docstrings":
                config_obj.docstrs = True
            case "-p" | "--keep-pyi-file":
                config_obj.pyi = True
            case "-T" | "--remove-tmp-dir":
                config_obj.keep_tmp = False
            case "-q" | "--no-quiet":
                config_obj.quiet = True
            case "-m" | "--show-modules":
                config_obj.show_mods = True
            case "--standalone":
                config_obj.mode = "standalone"
            case "--onefile":
                config_obj.mode = "onefile"
            case "--clang":
                config_obj.compiler = "clang"
            case "-R" | "--no-rename":
                config_obj.rename = False
            case "-u" | "--dry-run":
                config_obj.dry_run = True
            # options
            case "-b" | "--build-dir":
                config_obj.build_dir = argv[i + 1]
                i += 1
            case "-i" | "--data-dir":
                config_obj.data_dirs.append(argv[i + 1])
                i += 1
            case "-n" | "--output-filename":
                config_obj.out_filename = argv[i + 1]
                i += 1
            # special
            case "--":
                parse_opts_flags = False
            case _:
                raise RuntimeError(
                    f"Should've never happened, but here we are. My dumbass forgot to include a case for an option/flag: {param}"
                )

        i += 1

    args_len = len(config_obj.args)
    if not (MIN_ARGS <= args_len <= MIN_ARGS):
        fatal(
            f"argument {"underflow" if args_len < MIN_ARGS else "overflow"}; {args_len} not in [{MIN_ARGS}, {MAX_ARGS}]",
            ret=RC.ARG_UNDERFLOW,
        )

    for i, arg in enumerate(config_obj.args):
        if i == 0:
            config_obj.file = arg

    return config_obj


###############################################################################
### ENTRY POINT
###############################################################################

def main() -> None:
    cwd = os.getcwd()
    toml_file = os.path.join(cwd, "pc-config.toml")
    debug(f"cwd: {cwd}")
    debug(f"toml config file: {toml_file}")

    config    = Config()
    toml_data = read_toml_file(toml_file)
    config    = get_config_from_toml(config, toml_data)
    config    = parse_args(config)
    debug(f"final config: {str(config)}")

    # not sys.executable as it'll point to current prog when compiled
    python_xble = sh.which("python3")
    if python_xble is None:
        fatal("cannot find Python", ret=RC.NO_PYTHON)
    python_xble_disp = condense_path(python_xble)
    info(f"using Python binary {python_xble_disp}")

    # input file
    file = config.file
    if file is None:
        fatal("no input file", ret=RC.NO_INPUT_FILE)
    file = os.path.abspath(os.path.expanduser(file))
    info(f"using input file {file}")

    base_nm        = os.path.splitext(os.path.basename(file))[0]
    build_dir_nm   = ("build" if config.build_dir is None else config.build_dir)
    out_filename   = (base_nm if config.out_filename is None else config.out_filename)
    build_dir      = os.path.join(cwd, build_dir_nm)
    build_dir_disp = condense_path(os.path.abspath(build_dir))
    tmp_dir        = os.path.join(cwd, "tmp")
    tmp_dir_disp   = condense_path(os.path.abspath(tmp_dir))

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
        f"--mode={config.mode}",
        "--follow-imports",
        f"--output-folder-name={build_dir_nm}",
        f"--output-dir={cwd}",
        f"--output-filename={out_filename}",
        "--no-deployment-flag=self-execution",
        "--python-flag=no_docstrings" if not config.docstrs          else "",
        "--lto=yes"                   if config.lto                  else "--lto=no",
        f"--{config.compiler}"        if config.compiler is not None else "",
        "--remove-output"             if not config.keep_tmp         else "",
        "--no-pyi-file"               if not config.pyi              else "",
        "--quiet"                     if config.quiet                else "",
        "--show-modules"              if config.show_mods            else "",
        *[
            f"--include-data-dir={dir_}={os.path.basename(os.path.abspath(dir_))}"
            for dir_ in config.data_dirs
        ],
        file,
    ]
    cmd = [i for i in cmd if i]

    if config.dry_run:
        pretty_prn_list_of_str(cmd)
        return

    if os.path.isdir(build_dir) and not config.force:
        fatal(f"build directory already exists: {build_dir}", ret=RC.BUILD_DIR_EXISTS)
    if os.path.isdir(tmp_dir) and not config.force:
        fatal(f"tmp directory already exists: {tmp_dir}", ret=RC.TMP_DIR_EXISTS)

    # remove previous build directory
    try:
        sh.rmtree(build_dir)
        info(f"removed existing build dir {build_dir_disp}")
    except FileNotFoundError:
        info(f"could not find existing previous build dir {build_dir_disp}; skipping")
    except PermissionError:
        fatal(
            f"access denied to remove existing build dir {build_dir_disp}",
            ret=RC.ACCESS_DENIED,
        )
    except sh.Error:
        fatal(
            f"cannot remove existing build dir {build_dir_disp}",
            ret=RC.CANT_REMOVE_BUILD_DIR,
        )

    # remove previous tmp directory
    try:
        sh.rmtree(tmp_dir)
        info(f"removed tmp dir {tmp_dir_disp}")
    except FileNotFoundError:
        info(f"could not find existing tmp dir {tmp_dir_disp}; skipping")
    except PermissionError:
        fatal(
            f"access denied to remove existing tmp dir {tmp_dir_disp}",
            ret=RC.ACCESS_DENIED,
        )
    except sh.Error:
        fatal(
          f"cannot remove existing tmp dir {tmp_dir_disp}",
          ret=RC.CANT_TMP_BUILD_DIR,
      )

    # actually fucking run
    proc_done = sp.run(cmd)
    if proc_done.returncode != 0:
        fatal(
            f"errors encountered; Nuitka exited with code {proc_done.returncode}",
            ret=RC.SOME_FUCKING_ERR,
        )

    # rename build.dist to build, build.build to tmp
    if config.rename:
        if config.keep_tmp:
            build_dot_build      = os.path.join(cwd, f"{build_dir}.build")
            build_dot_build_disp = condense_path(os.path.abspath(build_dot_build))
            sh.move(build_dot_build, tmp_dir)
            info(f"moved {build_dot_build_disp} to {tmp_dir_disp}")
        build_dot_dist      = os.path.join(cwd, f"{build_dir}.dist")
        build_dot_dist_disp = condense_path(os.path.abspath(build_dot_dist))
        sh.move(build_dot_dist, build_dir)
        info(f"moved {build_dot_dist_disp} to {build_dir_disp}")

    # run output program
    if config.run:
        out_xble = os.path.join(build_dir, out_filename)
        info(f"running {out_xble}")
        sp.run([out_xble])


if __name__ == "__main__":
    main()
