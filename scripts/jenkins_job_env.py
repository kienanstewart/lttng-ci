#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2024 Kienan Stewart <kstewart@efficios.com>
# SPDX-License-Identifier: GPL-2.0-only
#

import argparse
import logging
import os
import pathlib
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib
import urllib.parse

_ENV_VARS = [
    "BABELTRACE_PLUGIN_PATH",
    "CPPFLAGS",
    "LD_LIBRARY_PATH",
    "LDFLAGS",
    "LIBBABELTRACE2_PLUGIN_PROVIDER_DIR",
    "LTTNG_CONSUMERD32_BIN",
    "LTTNG_CONSUMERD64_BIN",
    "LTTNG_SESSION_CONFIG_XSD_PATH",
    "PATH",
    "PKG_CONFIG_PATH",
    "PYTHONPATH",
    "WORKSPACE",
]


def fetch_url(url, destination):
    if shutil.which("wget"):
        subprocess.run(["wget", url, "-O", destination], check=True)
    elif shutil.which("curl"):
        subprocess.run(["curl", "--output", destination, url], check=True)
    else:
        raise Exception("No downloaded available")


def _get_argparser():
    parser = argparse.ArgumentParser(
        description="Fetch and create a stub environment from common job artifacts",
    )
    # Commands: fetch (implies activate), activate, deactivate
    subparsers = parser.add_subparsers(dest="command")
    parser.add_argument(
        "-v", "--verbose", action="count", help="Increase the verbosity"
    )

    fetch_parser = subparsers.add_parser("fetch")
    fetch_parser.add_argument(
        "directory",
        help="The directory",
        type=pathlib.Path,
    )
    fetch_parser.add_argument(
        "-f",
        "--file",
        default=None,
        type=pathlib.Path,
        help="An archive file downloaded from Jenkins",
    )
    fetch_parser.add_argument(
        "-s",
        "--server",
        default="https://ci.lttng.org",
        help="The jenkins server to use",
    )
    fetch_parser.add_argument(
        "-j",
        "--job",
        help="The job name, eg. 'lttng-tools_master_root_slesbuild'",
        default=None,
    )
    fetch_parser.add_argument(
        "-jc",
        "--job-configuration",
        help="An optional job configuration, eg. 'babeltrace_version=stable-2.0,build=std,conf=agents,liburcu_version=master,node=sles15sp4-amd64-rootnode,platform=sles15sp4-amd64'",
        default=None,
    )
    fetch_parser.add_argument(
        "-b", "--build-id", help="The build ID, eg. '28'", default=None
    )
    fetch_parser.add_argument(
        "-u",
        "--url",
        help="A URL from which to download the artifacts archive ZIP file",
        default=None,
    )
    fetch_parser.add_argument(
        "-n",
        "--no-download",
        help="Do not activate environment after fetching artifacts",
        action="store_false",
        dest="download",
        default=True,
    )

    return parser


def get_lib_dir():
    lib_dir = "lib"
    lib_dir_arch = lib_dir
    if (
        pathlib.Path("/etc/products.d/SLES.prod").exists()
        or pathlib.Path("/etc/redhat-release").exists()
        or pathlib.Path("/etc/yocto-release").exists()
        or "yocto" in platform.uname().release
    ) and "64bit" in platform.architecture():
        lib_dir_arch = "{}64".format(lib_dir)

    return lib_dir_arch


def fetch(
    destination,
    server,
    url=None,
    download=True,
    archive_file=None,
):
    if destination.exists() and not destination.is_dir():
        raise Exception("'{}' exists but is not a directory".format(str(destination)))

    if not destination.exists():
        destination.mkdir()

    if archive_file is not None and not archive_file.is_file():
        raise Exception(
            "Archive file '{}' given, but it is not a file".format(str(archive_file))
        )

    if url is not None and download:
        logging.info("Fetching archive from '{}'".format(url))

        with tempfile.NamedTemporaryFile() as archive:
            fetch_url(url, archive.name)
            subprocess.run(["unzip", "-d", str(destination), archive.name])

    if archive_file is not None:
        subprocess.run(["unzip", "-d", str(destination), str(archive_file)], check=True)

    if destination.is_dir():
        # The artifact archive doesn't include symlinks, so the the symlinks for
        # the ".so" in libdir_arch must be rebuilt
        lib_dir_arch = get_lib_dir()
        for x in (
            (destination / "archive" / "deps" / "build" / lib_dir_arch),
            (destination / "archive" / "build" / lib_dir_arch),
        ):
            add_lib_symlinks(x)

        # If an unclean src archive, exists, unpack it.
        src_archive = (destination / "archive" / "src.tar.xz").absolute()
        if src_archive.is_file():
            src_dir = (destination / "archive" / "src").absolute()
            if not src_dir.is_dir():
                os.mkdir(str(src_dir))

            subprocess.run(
                ["tar", "-x", "-f", str(src_archive)],
                check=True,
                cwd=str(src_dir),
            )

    env = create_activate(destination)
    create_deactivate(destination, env)


def add_lib_symlinks(directory):
    so_re = re.compile(r"^.*\.so\.\d+\.\d+\.\d+$")
    for root, dirs, files in os.walk(str(directory)):
        for f in files:
            if so_re.match(f):
                bits = f.split(".")
                alts = [
                    os.path.join(root, ".".join(bits[:-1])),
                    os.path.join(root, ".".join(bits[:-2])),
                    os.path.join(root, ".".join(bits[:-3])),
                ]
                for a in [alt for alt in alts if not os.path.exists(alt)]:
                    os.symlink(f, a)


def create_activate(destination):
    lib_dir_arch = get_lib_dir()
    env = {}
    env["_JENKINS_ENV"] = destination.name
    archive_dir = (destination / "archive").absolute()
    for var in _ENV_VARS:
        original = os.getenv(var)
        env["_JENKINS_{}".format(var)] = original if original else ""
        if var == "BABELTRACE_PLUGIN_PATH":
            env["BABELTRACE_PLUGIN_PATH"] = "{}{}".format(
                "{}:".format(original) if original else "",
                str(
                    (
                        destination
                        / "archive"
                        / "deps"
                        / "build"
                        / lib_dir_arch
                        / "babeltrace2"
                        / "plugins"
                    ).absolute()
                ),
            )
        elif var == "CPPFLAGS":
            env["CPPFLAGS"] = "{}-I{}".format(
                "{} ".format(original) if original else "",
                str(
                    (destination / "archive" / "deps" / "build" / "include").absolute()
                ),
            )
        elif var == "LD_LIBRARY_PATH":
            paths = [
                str((destination / "archive" / "build" / lib_dir_arch).absolute()),
                str(
                    (
                        destination / "archive" / "deps" / "build" / lib_dir_arch
                    ).absolute()
                ),
            ]

            if os.getenv("LD_LIBRARY_PATH"):
                paths.append(os.getenv("LD_LIBRARY_PATH"))

            env["LD_LIBRARY_PATH"] = ":".join(paths)
        elif var == "LDFLAGS":
            env["LDFLAGS"] = "{}-L{}".format(
                "{} ".format(original) if original else "",
                str(
                    (
                        destination / "archive" / "deps" / "build" / lib_dir_arch
                    ).absolute()
                ),
            )
        elif var == "LIBBABELTRACE2_PLUGIN_PROVIDER_DIR":
            if not archive_dir.exists():
                logging.warning("Assuming '{}' value since archive is not downloaded")
                env["LIBBABELTRACE2_PLUGIN_PROVIDER_DIR"] = str(
                    archive_dir
                    / "deps"
                    / "build"
                    / libdir_arch
                    / "babeltrace2"
                    / "plugin-providers"
                )
            else:
                for entry in archive_dir.glob("**/babeltrace2/plugin-providers"):
                    if entry.is_dir() and var not in env:
                        env[var] = str(entry.absolute())
        elif var in ["LTTNG_CONSUMERD32_BIN", "LTTNG_CONSUMERD64_BIN"]:
            if not archive_dir.exists():
                logging.warning(
                    "Assuming '{}' value since archive is not downloaded".format(var)
                )
                env[var] = str(
                    archive_dir
                    / "build"
                    / libdir_arch
                    / "lttng"
                    / "libexec"
                    / "lttng-consumerd"
                )
            else:
                for entry in archive_dir.glob("**/lttng/libexec/lttng-consumerd"):
                    if entry.is_file() and var not in env:
                        env[var] = str(entry)
        elif var == "LTTNG_SESSION_CONFIG_XSD_PATH":
            if not archive_dir.exists():
                logging.warning(
                    "Assuming '{}' value since archive is not downloaded".format(var)
                )
                env[var] = str(archive_dir / "build" / "share" / "xml" / "lttng")
            else:
                for entry in archive_dir.glob("**/session.xsd"):
                    if entry.is_file() and var not in env:
                        env[var] = str(entry.parents[0])
        elif var == "PATH":
            paths = [
                str((destination / "archive" / "build" / "bin").absolute()),
                str((destination / "archive" / "deps" / "build" / "bin").absolute()),
                os.getenv("PATH"),
            ]

            env["PATH"] = ":".join(paths)
        elif var == "PKG_CONFIG_PATH":
            env["PKG_CONFIG_PATH"] = "{}{}".format(
                "{}:" if original else "",
                str(
                    (
                        destination
                        / "archive"
                        / "deps"
                        / "build"
                        / lib_dir_arch
                        / "pkgconfig"
                    ).absolute()
                ),
            )
        elif var == "PYTHONPATH":
            # This searches the downloaded archive for matching directories
            if not (archive_dir).exists():
                logging.warning(
                    "PYTHONPATH not set in activate as it requires the artifacts to be downloaded first"
                )
            else:
                python_paths = list()
                for entry in archive_dir.glob("**/site-packages"):
                    if entry.is_dir():
                        python_paths.append(str(entry.absolute()))

                if os.getenv("PYTHONPATH"):
                    python_paths.append(os.getenv("PYTHONPATH"))

                if python_paths:
                    env["PYTHONPATH"] = ":".join(python_paths)
        elif var == "WORKSPACE":
            env["WORKSPACE"] = str((destination / "archive").absolute())
        else:
            logging.warning("Not supported: {}".format(var))
            # raise Exception("Unsupported environment variable '{}'".format(var))

    args = ["{}={}".format(k, shlex.quote(v)) for k, v in env.items()]
    with open(str(destination / "activate"), "w") as fp:
        fp.writelines("#!/usr/bin/bash\n")
        for arg in args:
            fp.writelines("export {}\n".format(arg))
    (destination / "activate").chmod(0o755)
    return env


def create_deactivate(destination, env):
    with open(str(destination / "deactivate"), "w") as fp:
        fp.writelines("#!/usr/bin/bash\n")
        for k, v in env.items():
            if k.startswith("_JENKINS_"):
                fp.writelines("unset {}\n".format(k))
            else:
                original = env["_JENKINS_{}".format(k)]
                fp.writelines("export {}={}\n".format(k, original))
    (destination / "deactivate").chmod(0o755)


if __name__ == "__main__":
    logger = logging.getLogger()
    parser = _get_argparser()
    args = parser.parse_args()
    logger.setLevel(max(1, 30 - (args.verbose or 0) * 10))
    logging.debug("Initialized with log level: {}".format(logger.getEffectiveLevel()))

    if args.command == "fetch":
        if args.file is None:
            # Assert that the other options are supplied
            if not args.url and (not args.build_id or not args.server or not args.job):
                raise Exception(
                    "When `-f|--file` is not given, either `-u|--url` or server (`-s|--server`), job (`-j|--job`), and build id (`-b|--build-id`) are required"
                )

        if args.url is None:
            # Assert that the other options are supplied
            if not args.file and (not args.build_id or not args.server or not args.job):
                raise Exception(
                    "When `-u|--url` is not given, either `-f|--file` or server (`-s|--server`), job (`-j|--job`), and build id (`-b|--build-id`) are required"
                )

        if args.url and args.file:
            raise Exception("Only one of `-f|--file` and `-u|--url` may be given")

        if args.file is None and args.url is None:
            # URL from compoenents
            components = [
                "job",
                args.job,
                args.job_configuration or "",
                args.build_,
                "artifact",
                "*zip*",
                "archive.zip",
            ]
            url_components = [urllib.parse.quote_plus(x) for x in components]
            url = "/".join([server] + url_components)
            args.url = url

        fetch(
            destination=args.directory,
            server=args.server,
            url=args.url,
            download=args.download,
            archive_file=args.file,
        )
    else:
        raise Exception("Command '{}' unsupported".format(args.command))
    sys.exit(0)
