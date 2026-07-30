#!/usr/bin/env python3
#
# SPDX-License-Identifier: GPL-2.0-only
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
#
# This script checks the most recent commit message of the project defined
# by GERRIT_NAME as checked out in $WORKSPACE/src/<project_name> for
# `Depends-On:` lines and fetches + checks out any dependencies that
# are not merged or abandoned.
#
# The intended workflow is for jobs to perform the initial checkouts into
# $WORKSPACE/src for each project before calling this script to resolve
# Depends-on lines in the commit message(s).
#

import json
import logging
import os
import pathlib
import re
import subprocess
import typing
import sys
import urllib.request


def gerrit_dependencies(
    project: str, source_directory: pathlib.Path, gerrit_host: str, gerrit_scheme: str
) -> typing.Dict[str, str]:
    depends_on_regex = re.compile(
        r"^Depends-on: (?P<project>lttng-ust|lttng-modules|userspace-rcu|babeltrace): (?P<change_id>[a-zA-Z0-9]*)$"
    )

    project_directory = source_directory / project
    if not project_directory.is_dir():
        raise RuntimeError(
            "Project directory '{}' does not exist or is not a directory".format(
                str(project_directory)
            )
        )

    p = subprocess.Popen(
        [
            "git",
            "-C",
            str(project_directory),
            "rev-list",
            "--format=%B",
            "--max-count=1",
            "HEAD",
        ],
        stdout=subprocess.PIPE,
        encoding="utf-8",
    )
    p.wait()

    if p.returncode != 0:
        raise RuntimeError(
            "Failed to get git revision: return code {}".format(p.returncode)
        )

    commit_log = p.stdout.read()
    logging.debug("Commit log: {}".format(commit_log))

    depends_on = dict()
    for line in commit_log.splitlines():
        m = depends_on_regex.search(line)
        if m is None:
            continue

        logging.info(
            "Discovered depends-on in project '{}': {} @ {}".format(
                project, m.group("project"), m.group("change_id")
            )
        )
        depends_on[m.group("project")] = m.group("change_id")

    return depends_on


def open_change_id_to_ref(
    project: str,
    change_id: str,
    gerrit_host: str,
    gerrit_scheme: str,
    match_branch: typing.Optional[str] = None,
) -> typing.Optional[str]:
    q = "change:{}+project:{}".format(change_id, project)
    if match_branch:
        q += "+branch:{}".format(match_branch)

    url = "{}://{}/changes?q={}&o=CURRENT_REVISION&o=DOWNLOAD_COMMANDS".format(
        gerrit_scheme, gerrit_host, q
    )
    req = urllib.request.Request(url=url)

    logging.info("URL: {}".format(url))
    result = None
    with urllib.request.urlopen(req) as f:
        x = f.read().decode("utf-8")
        try:
            # The gerrit API returns a first magic line ")]}'" which must be stripped
            if x.startswith(")]}'\n"):
                x = x[5:]

            result = json.loads(x)
        except Exception as e:
            print(x)
            logging.exception("Failed to parse JSON response")
            raise e
        # result = json.loads()

    if not result:
        raise RuntimeError("No response object for change: {}".format(change_id))

    if len(result) > 1:
        logging.warn(
            "Multiple results for {} change '{}', using the first".format(
                project, change_id
            )
        )

    change_status = result[0]["status"]
    if change_status in ["ABANDONED", "MERGED"]:
        logging.info(
            "{} change '{}' is {}: skipping".format(project, change_id, change_status)
        )
        return

    current_revision = result[0]["current_revision"]
    return result[0]["revisions"][current_revision]["ref"]


def project_checkout_ref(
    project: str,
    ref: str,
    source_directory: pathlib.Path,
    gerrit_host: str,
    gerrit_scheme: str,
    skip_fetch: bool = False,
):
    checkout_target = ref
    if not skip_fetch:
        fetch_target = "{}://{}/{}.git".format(gerrit_scheme, gerrit_host, project)
        logging.info("Fetching ref '{}' from {}".format(ref, fetch_target))
        p = subprocess.Popen(
            ["git", "-C", str(source_directory / project), "fetch", fetch_target, ref]
        )
        p.wait()
        if p.returncode != 0:
            raise RuntimeError(
                "git fetch returned non-zero exit-code: {}".format(p.returncode)
            )

        checkout_target = "FETCH_HEAD"

    p = subprocess.Popen(
        ["git", "-C", str(source_directory / project), "checkout", checkout_target]
    )
    p.wait()
    if p.returncode != 0:
        raise RuntimeError(
            "git checkout returned non-zero exit-code: {}".format(p.returncode)
        )


def _main(
    gerrit_project: str,
    source_directory: pathlib.Path,
    gerrit_host: str,
    gerrit_scheme: str,
    handled_projects: typing.Dict = dict(),
    skip_fetch: bool = False,
):
    if not handled_projects:
        handled_projects[gerrit_project] = "HEAD"

    deps = gerrit_dependencies(
        gerrit_project, source_directory, gerrit_host, gerrit_scheme
    )
    for project, change_id in deps.items():
        if project in handled_projects:
            raise RuntimeError(
                "Recursive dependency '{}': {} at {}. Previous change: {}".format(
                    project,
                    remote,
                    reference,
                    handled_projects[project],
                )
            )

        logging.info("Checking depends-on '{}': {}".format(project, change_id))
        project_ref = open_change_id_to_ref(
            project, change_id, gerrit_host, gerrit_scheme
        )
        if not project_ref:
            continue

        logging.info("Checking out ref '{}' for {}".format(project_ref, project))
        project_checkout_ref(
            project,
            project_ref,
            source_directory,
            gerrit_host,
            gerrit_scheme,
            skip_fetch=skip_fetch,
        )
        handled_projects[project] = change_id

        # Handle recursive depends-on
        _main(
            project,
            source_directory,
            gerrit_host,
            gerrit_scheme,
            handled_projects,
            skip_fetch=skip_fetch,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    gerrit_project = os.getenv("GERRIT_PROJECT", None)
    if not gerrit_project:
        logging.info("GERRIT_PROJECT not set")
        sys.exit(0)

    workspace = pathlib.Path(os.getenv("WORKSPACE", os.getcwd()))
    source_directory = workspace / "src"

    gerrit_host = os.getenv("GERRIT_HOST", None)
    gerrit_scheme = os.getenv("GERRIT_SCHEME", "https")

    if not gerrit_host:
        logging.info("GERRIT_HOST not set")
        sys.exit(0)

    try:
        _main(gerrit_project, source_directory, gerrit_host, gerrit_scheme)
    except Exception as e:
        logging.exception("Unhandled exception")
        sys.exit(1)
