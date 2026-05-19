#!/usr/bin/env python3
#
# SPDX-License-Identifier: GPL-2.0-only
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
#

import contextlib
import json
import pathlib
import subprocess
import sys

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "scripts" / "common"))
import s3conf


def env_has_s3_authentication():
    return pytest.mark.skipif(
        not s3conf.S3_SECRET_KEY or not s3conf.S3_ACCESS_KEY,
        reason="No S3 access in environment variables",
    )


@contextlib.contextmanager
def git_branch(repo, b):
    subprocess.run(["git", "-C", str(repo), "checkout", b], check=True)
    yield
    subprocess.run(["git", "-C", str(repo), "checkout", "master"], check=True)


@pytest.fixture(scope="session")
def babeltrace_repo(tmp_path_factory):
    repo_dir = tmp_path_factory.mktemp("babeltrace")
    subprocess.run(
        [
            "git",
            "clone",
            "https://github.com/efficios/babeltrace.git",
            str(repo_dir),
        ],
        check=True,
    )
    yield repo_dir


@pytest.fixture(scope="session")
def benchmark_script_path():
    yield (
        pathlib.Path(__file__).parents[1]
        / "scripts"
        / "babeltrace-benchmark"
        / "benchmark.py"
    )


@env_has_s3_authentication()
def test_cli_generate_jobs(babeltrace_repo, benchmark_script_path, tmp_path):
    output = tmp_path / "output"
    commits = [
        "6ff4008c16f49aa0bb24570bfb1e27ff0df58d65",
        "ae7b8e0a1e942b656233be9c648a27f5cb9a585e",
        "06df58f89ee51b1a2c6a2c187ec3f15691633910",
        "4772a04217336203fa6310aadf511e9c159d6f13",
        "ab2d8acd34eb91faca00878f6851839ed5188e93",
        "c85dbd471b37fc696cdd35298d6bc5505bcc74b4",
        "2de442b9b2afcbaccc4f7313495f866cb34920b8",
        "978b18de74be0b63ec896cca09ff5a8ab61ea156",
        "3db793e7f1a553587e96efdc6e063837f5ff93c5",
        "b007e40bc133f5d8606886b18043ef894817d9ab",
        "33003c352ed56aa49e0b3df272bbab6fac36cae8",
        "2848997edd14420817fde28e8651fc7d86d15067",
        "40dc9e54dfad83dd06e16ea147b6ec8f341cf1dd",
        "41e53c9eddcf8c2cc67ca9780a8f1d9fcae2a0fd",
        "b59b6a3d9fc737ec112756410db77fa87e6e1c93",
        "b348a2faaef87a86f36bc83a30ec96713a138d78",
        "f03270cbbfa1902182b064ae2af324b045ff5cb0",
    ]
    args = [
        str(benchmark_script_path),
        "--bt-repo-path",
        str(babeltrace_repo),
        "--generate-jobs",
        "--dry-run",
        "--force",
        "--tags-only",
        "--overwrite-branches-cutoff",
        json.dumps({"stable-2.0": "a"}),
    ]

    p = subprocess.Popen(args, stdout=open(output, "w"))
    p.wait()
    assert p.returncode == 0

    with open(output, "r") as f:
        job = yaml.load(f, yaml.SafeLoader)

    job_commits = job["environment"]["BT_COMMITS"].split(" ")
    assert len(job_commits) == len(commits)
    for commit in commits:
        assert commit in job_commits


@env_has_s3_authentication()
def test_cli_generate_jobs_regression(babeltrace_repo, benchmark_script_path, tmp_path):
    output = tmp_path / "output"
    commits = [
        "e61d41ff3c3ac6a123930d4e60cf710ff9ea18e0",
        "5fd84a3027bd00f943e297a08c41b75c6391f25b",
        "5cd907e34d5df862835a23d4b3d3f4d54c24ed3b",
    ]
    args = [
        str(benchmark_script_path),
        "--bt-repo-path",
        str(babeltrace_repo),
        "--generate-regression-jobs",
        "--dry-run",
        "--force",
        "--tags-only",
        "--current-commit",
        "v2.0.7",
    ]

    p = subprocess.Popen(args, stdout=open(output, "w"))
    p.wait()
    assert p.returncode == 0

    with open(output, "r") as f:
        job = yaml.load(f, yaml.SafeLoader)

    job_commits = job["environment"]["BT_COMMITS"].split(" ")
    assert len(job_commits) == len(commits)
    for commit in commits:
        assert commit in job_commits


@env_has_s3_authentication()
def test_cli_generate_report(babeltrace_repo, benchmark_script_path, tmp_path):
    output = tmp_path / "output"
    report = tmp_path / "report.pdf"
    args = [
        str(benchmark_script_path),
        "--bt-repo-path",
        str(babeltrace_repo),
        "--generate-report",
        "--tags-only",
        "--overwrite-branches-cutoff",
        json.dumps({"stable-2.0": "a"}),
        "--report-name",
        str(report),
    ]

    p = subprocess.Popen(args, stdout=open(output, "w"))
    p.wait()
    assert p.returncode == 0
    assert report.is_file()


@env_has_s3_authentication()
def test_cli_generate_asv(babeltrace_repo, benchmark_script_path, tmp_path):
    with git_branch(babeltrace_repo, "stable-2.0"):
        output = tmp_path / "output"
        report = tmp_path / "report"
        args = [
            str(benchmark_script_path),
            "--bt-repo-path",
            str(babeltrace_repo),
            "--generate-asv-report",
            "--tags-only",
            "--overwrite-branches-cutoff",
            json.dumps({"stable-2.0": "a"}),
            "--asv-output-dir",
            str(report),
        ]

        p = subprocess.Popen(args, stdout=open(output, "w"))
        p.wait()
        assert p.returncode == 0
        assert report.is_dir()
        assert (report / "index.html").is_file()


@env_has_s3_authentication()
def test_cli_check_regression_results(babeltrace_repo, benchmark_script_path, tmp_path):
    output = tmp_path / "output"
    stderr = tmp_path / "error"
    report = tmp_path / "report"
    commits = [
        "b348a2faaef87a86f36bc83a30ec96713a138d78",
        "2848997edd14420817fde28e8651fc7d86d15067",
        "6ff4008c16f49aa0bb24570bfb1e27ff0df58d65",
    ]
    args = [
        str(benchmark_script_path),
        "--bt-repo-path",
        str(babeltrace_repo),
        "--check-regression-results",
        "--current-commit",
        commits[0],
        "--other-commits",
        ",".join(commits[1:]),
    ]

    p = subprocess.Popen(args, stdout=open(output, "w"), stderr=open(stderr, "w"))
    p.wait()

    with open(stderr, "r") as f:
        stderr_lines = f.readlines()

    regression_detected = False
    for line in stderr_lines:
        if line.find("Regression detected in benchmark") != -1:
            regression_detected = True

    returncode_expected = 1 if regression_detected else 0
    assert p.returncode == returncode_expected
