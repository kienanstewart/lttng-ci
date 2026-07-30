#!/usr/bin/env python3
#
# SPDX-License-Identifier: GPL-2.0-only
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
#

import json
import pathlib
import subprocess
import sys

import pytest
import pytest_httpserver

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "lib" / "resources"))

print(sys.path)
import gerrit_depends_on


@pytest.fixture(scope="session")
def workspace(tmp_path_factory):
    yield tmp_path_factory.mktemp("workspace")


def project_git_repo(project_name, workspace):
    src_dir = workspace / "src"
    src_dir.mkdir(exist_ok=True)

    project_dir = src_dir / project_name
    if project_dir.is_dir():
        return project_dir

    p = subprocess.Popen(["git", "init", str(project_dir)])
    p.wait()
    assert p.returncode == 0

    p = subprocess.Popen(
        [
            "git",
            "-C",
            str(project_dir),
            "commit",
            "--allow-empty",
            "-m",
            "Initial commit",
        ],
    )
    p.wait()
    assert p.returncode == 0

    return project_dir


@pytest.fixture()
def lttng_tools_repo(workspace):
    yield project_git_repo("lttng-tools", workspace)


@pytest.fixture()
def lttng_ust_repo(workspace):
    yield project_git_repo("lttng-ust", workspace)


@pytest.fixture()
def babeltrace_repo(workspace):
    yield project_git_repo("babeltrace", workspace)


@pytest.fixture()
def userspace_rcu_repo(workspace):
    yield project_git_repo("userspace-rcu", workspace)


def gerrit_data_str(data: dict) -> str:
    return ")]}'\n" + json.dumps(data)


# Test a recursive resolution of Depends-on.
#
# lttng-tools -> depends-on: lttng-ust, depends-on: babeltrace
# lttng-ust -> depends-on: userspace-rcu
#
def test_recursive_resolution(
    workspace,
    lttng_tools_repo,
    lttng_ust_repo,
    userspace_rcu_repo,
    babeltrace_repo,
    httpserver: pytest_httpserver.HTTPServer,
):
    # Add commit with lttng-tools
    # Depends-on: lttng-ust: XXX
    # Depends-on: babeltrace: YYY
    message = "Test commit\n\nDepends-on: lttng-ust: XXX\nDepends-on: babeltrace: YYY\nSigned-off-by: Fake\n"
    p = subprocess.Popen(
        ["git", "-C", str(lttng_tools_repo), "commit", "--allow-empty", "-m", message],
    )
    p.wait()
    assert p.returncode == 0

    lttng_ust_ref = "refs/changes/21/1021/1"
    lttng_ust_data = [
        {
            "status": "OPEN",
            "current_revision": "X",
            "revisions": {
                "X": {
                    "ref": lttng_ust_ref,
                },
            },
        }
    ]

    # Add commit to lttng-ust a the given ref with depends-on
    commands = [
        ["git", "-C", str(lttng_ust_repo), "checkout", "-b", lttng_ust_ref],
        [
            "git",
            "-C",
            str(lttng_ust_repo),
            "commit",
            "--allow-empty",
            "-m",
            "Test commit\n\nDepends-on: userspace-rcu: ZZZ\n",
        ],
        ["git", "-C", str(lttng_ust_repo), "checkout", "main"],
    ]
    for command in commands:
        p = subprocess.Popen(command)
        p.wait()
        assert p.returncode == 0

    babeltrace_ref = "refs/changes/X/XXXXX/X"
    babeltrace_data = [
        {
            "status": "OPEN",
            "current_revision": "X",
            "revisions": {
                "X": {
                    "ref": babeltrace_ref,
                },
            },
        }
    ]

    commands = [
        ["git", "-C", str(babeltrace_repo), "checkout", "-b", babeltrace_ref],
        [
            "git",
            "-C",
            str(babeltrace_repo),
            "commit",
            "--allow-empty",
            "-m",
            "Test commit",
        ],
        ["git", "-C", str(babeltrace_repo), "checkout", "main"],
    ]
    for command in commands:
        p = subprocess.Popen(command)
        p.wait()
        assert p.returncode == 0

    userspace_rcu_ref = "refs/change/weee"
    userspace_rcu_data = [
        {
            "status": "OPEN",
            "current_revision": "X",
            "revisions": {
                "X": {
                    "ref": userspace_rcu_ref,
                },
            },
        }
    ]
    commands = [
        ["git", "-C", str(userspace_rcu_repo), "checkout", "-b", userspace_rcu_ref],
        [
            "git",
            "-C",
            str(userspace_rcu_repo),
            "commit",
            "--allow-empty",
            "-m",
            "Test commit",
        ],
        ["git", "-C", str(userspace_rcu_repo), "checkout", "main"],
    ]
    for command in commands:
        p = subprocess.Popen(command)
        p.wait()
        assert p.returncode == 0

    httpserver.expect_request(
        "/changes",
        query_string="q=change:XXX+project:lttng-ust&o=CURRENT_REVISION&o=DOWNLOAD_COMMANDS",
    ).respond_with_data(gerrit_data_str(lttng_ust_data))

    httpserver.expect_request(
        "/changes",
        query_string="q=change:YYY+project:babeltrace&o=CURRENT_REVISION&o=DOWNLOAD_COMMANDS",
    ).respond_with_data(gerrit_data_str(babeltrace_data))

    httpserver.expect_request(
        "/changes",
        query_string="q=change:ZZZ+project:userspace-rcu&o=CURRENT_REVISION&o=DOWNLOAD_COMMANDS",
    ).respond_with_data(gerrit_data_str(userspace_rcu_data))

    gerrit_depends_on._main(
        "lttng-tools",
        workspace / "src",
        "{}:{}".format(httpserver.host, httpserver.port),
        "http",
        # For testing, don't run git fetch but just checkout the supplied ref directly
        # When this is not specified (the default), the script will run `git fetch` against
        # the gerrit host (in this case, the mock httpserver), and I don't feel like mocking
        # the entire git protocol.
        skip_fetch=True,
    )

    # Assert that the repos are checked out to the branches resolved from the gerrit responses
    expectations = [
        (lttng_ust_repo, lttng_ust_ref),
        (babeltrace_repo, babeltrace_ref),
        (userspace_rcu_repo, userspace_rcu_ref),
    ]
    for repo, ref in expectations:
        p = subprocess.Popen(
            ["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
            stdout=subprocess.PIPE,
        )
        p.wait()
        assert p.returncode == 0
        assert p.stdout.read().decode("utf-8").split()[0] == ref
