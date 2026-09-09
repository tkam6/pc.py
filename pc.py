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

DEBUG   = 10
INFO    = 20
WARN    = 30
ERR     = 40
FATAL   = 50
LOG_LVL = INFO

MIN_ARGS = 0
MAX_ARGS = 1

VALID_FLAGS = {
    "--",
    "--clang",
    "--onefile",
    "--standalone",
    "--keep-pyi-file",
    "-d", "--debug",
    "-f", "--force",
    "-h", "--help",
    "-i", "--info",
    "-l", "--enable-lto",
    "-m", "--show-modules",
    "-q", "--quiet",
    "-R", "--no-rename",
    "-s", "--keep-docstrings",
    "-r", "--run",
    "-T", "--remove-tmp-dir",
    "-u", "--dry-run",
}
VALID_OPTS = {
    "-b", "--build-dir",
    "-n", "--output-filename",
    "-p", "--package",
    "-a", "--raw-dir",
    "-y", "--full-dir",
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
    "output-filename": "out_filename",
    "file"           : "file",
}
VALID_TOML_LIST_KEYS = {
    "full-directories": "full_dirs",
    "raw-files"       : "raw_files",
    "packages"        : "pkgs",
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
    file        : str | None = None
    full_dirs   : list[str]  = dcs.field(default_factory=list)
    docstrs     : bool       = False
    dry_run     : bool       = False
    force       : bool       = False
    keep_tmp    : bool       = True
    log_lvl     : int        = WARN
    lto         : bool       = False
    mode        : str        = "standalone"
    out_filename: str | None = None
    quiet       : bool       = False
    pkgs        : list[str]  = dcs.field(default_factory=list)
    pyi         : bool       = False
    raw_files   : list[str]  = dcs.field(default_factory=list)
    rename      : bool       = True
    run         : bool       = False
    show_mods   : bool       = False


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
    if LOG_LVL <= DEBUG:
        print(f"{ANSI_BOLD}D:{ANSI_RESET}", *msg, file=sys.stderr)

def info(*msg: str) -> None:
    if LOG_LVL <= INFO:
        print(f"{ANSI_BOLD}I:{ANSI_RESET}", *msg, file=sys.stderr)

def warn(*msg: str) -> None:
    if LOG_LVL <= WARN:
        print(f"{ANSI_BOLD}{ANSI_YELLOW_4}W:{ANSI_RESET}", *msg, file=sys.stderr)

def err(*msg: str) -> None:
    if LOG_LVL <= ERR:
        print(f"{ANSI_BOLD}{ANSI_RED_4}E:{ANSI_RESET}", *msg, file=sys.stderr)

def fatal(*msg: str, ret: int) -> ty.NoReturn:
    if LOG_LVL <= FATAL:
        print(f"{ANSI_BOLD}{ANSI_RED_4}F:{ANSI_RESET}", *msg, file=sys.stderr)
    sys.exit(ret)


###############################################################################
### CONFIG FILE
###############################################################################

def read_toml_file(filepath: str) -> dict[str, ty.Any] | ty.NoReturn:
    try:
        contents =  tl.load(f := open(filepath, "rb"))
        f.close()
        return contents
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
        elif key in VALID_TOML_LIST_KEYS and not isinstance(value, list):
            fatal(
                f"expected list of strs for key {key} in config file, got {value.__class__.__name__}",
                ret=RC.TOML_INV_TYPE,
            )
        elif key in VALID_TOML_LIST_KEYS and (tmp := [i for i in value if not isinstance(i, str)]):
            fatal(
                f"expected list of strs key {key} in config file, got other types",
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
        elif key in VALID_TOML_LIST_KEYS:
            setattr(config_obj, VALID_TOML_LIST_KEYS[key], value)

    return config_obj


###############################################################################
### ARGV PARSING
###############################################################################

def parse_args(config_obj: Config) -> Config:
    argv              = sys.argv[1:]
    parse_opts_flags  = True
    len_argv          = len(argv)
    i                 = 0
    alr_set_full_dirs = bool(config_obj.full_dirs)
    alr_set_raw_files = bool(config_obj.raw_files)
    alr_set_pkgs      = bool(config_obj.pkgs)

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
            case "-d" | "--debug":
                config_obj.log_lvl = DEBUG
            case "-f" | "--force":
                config_obj.force = True
            case "-i" | "--info":
                config_obj.log_lvl = INFO
            case "-l" | "--enable-lto":
                config_obj.lto = True
            case "-m" | "--show-modules":
                config_obj.show_mods = True
            case "--keep-pyi-file":
                config_obj.pyi = True
            case "-q" | "--quiet":
                config_obj.quiet = True
            case "-R" | "--no-rename":
                config_obj.rename = False
            case "-r" | "--run":
                config_obj.run = True
            case "-s" | "--keep-docstrings":
                config_obj.docstrs = True
            case "-T" | "--remove-tmp-dir":
                config_obj.keep_tmp = False
            case "-u" | "--dry-run":
                config_obj.dry_run = True
            case "--standalone":
                config_obj.mode = "standalone"
            case "--onefile":
                config_obj.mode = "onefile"
            case "--clang":
                config_obj.compiler = "clang"
            # options
            case "-b" | "--build-dir":
                config_obj.build_dir = argv[i + 1]
                i += 1
            case "-n" | "--output-filename":
                config_obj.out_filename = argv[i + 1]
                i += 1
            case "-p" | "--package":
                if alr_set_pkgs:
                    config_obj.pkgs = []
                    alr_set_pkgs = False
                config_obj.pkgs.append(argv[i + 1])
            case "-a" | "--raw-file":
                if alr_set_raw_files:
                    config_obj.raw_files = []
                    alr_set_raw_files = False
                config_obj.raw_files.append(argv[i + 1])
            case "-y" | "--full-dir":
                if alr_set_full_dirs:
                    config_obj.full_dirs = []
                    alr_set_full_dirs = False
                config_obj.full_dirs.append(argv[i + 1])
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
    if not (MIN_ARGS <= args_len <= MAX_ARGS):
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
    # manage execution of instructions and behaviour following non-fatal problems
    non_fatal = False

    cwd = os.getcwd()
    toml_file = os.path.join(cwd, "pc-config.toml")

    config    = Config()
    toml_data = read_toml_file(toml_file)
    config    = get_config_from_toml(config, toml_data)
    config    = parse_args(config)

    global LOG_LVL
    LOG_LVL = config.log_lvl
    debug(f"cwd: {cwd}")
    debug(f"toml config file: {toml_file}")
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
        *[f"--include-package={pkg}"  for pkg in config.pkgs],
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

    # copy full dirs into dist dir
    for dir_ in config.full_dirs:
        try:
            dir_abs = os.path.abspath(os.path.expanduser(dir_))
            sh.copytree(dir_abs, os.path.join(build_dir, os.path.basename(dir_abs)))
            debug(f"full-copied {dir_}")
        except FileNotFoundError:
            err(f"cannot find {dir_} to full copy")
            non_fatal = True
        except PermissionError:
            err(f"access denied to {dir_} to full copy")
            non_fatal = True
        except OSError as e:
            err(f"OS error: {e.strerror}")
            non_fatal = True
        except sh.Error as e:
            err(f"copy error: {e}")
            non_fatal = True

    for file in config.raw_files:
        try:
            file_abs = os.path.abspath(os.path.expanduser(file))
            sh.copy2(file_abs, build_dir)
            debug(f"raw-copied {file}")
        except FileNotFoundError:
            err(f"cannot find {file} to raw copy")
            non_fatal = True
        except PermissionError:
            err(f"access denied to {file} to raw copy")
            non_fatal = True
        except OSError as e:
            err(f"OS error: {e.strerror}")
            non_fatal = True

    # run output program
    if config.run:
        if non_fatal:
            warn("skipping run due to previous errors")
        else:
            out_xble = os.path.join(build_dir, out_filename)
            info(f"running {out_xble}")
            sp.run([out_xble])


if __name__ == "__main__":
    main()
