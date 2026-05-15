#!/usr/bin/env python3
#
# SPDX-License-Identifier: GPL-2.0-only
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
#

import pathlib
import subprocess

import pytest
import yaml


@pytest.fixture(scope="session")
def lttng_ust_repo(tmp_path_factory):
    repo_dir = tmp_path_factory.mktemp("lttng-ust")
    subprocess.run(
        [
            "git",
            "clone",
            "https://github.com/lttng/lttng-ust.git",
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
        / "lttng-ust-benchmarks"
        / "benchmark.py"
    )


def test_cli_gen_asv(benchmark_script_path, tmp_path, lttng_ust_repo):
    output = tmp_path / "output"
    asv_dir = tmp_path / "asv"
    data_files = [
        pathlib.Path(__file__).parents[0]
        / "data"
        / "lttng-ust-benchmarks"
        / "2.13.0.json",
        pathlib.Path(__file__).parents[0]
        / "data"
        / "lttng-ust-benchmarks"
        / "2.13.1.json",
        pathlib.Path(__file__).parents[0]
        / "data"
        / "lttng-ust-benchmarks"
        / "2.13.2.json",
        pathlib.Path(__file__).parents[0]
        / "data"
        / "lttng-ust-benchmarks"
        / "2.13.10.json",
    ]
    args = [
        str(benchmark_script_path),
        "--repo-path",
        str(lttng_ust_repo),
        "generate-asv",
        "-o",
        str(asv_dir),
    ]
    for data_file in data_files:
        args.extend(["-i", str(data_file)])

    p = subprocess.Popen(args, stdout=open(output, "w"))
    p.wait()
    assert p.returncode == 0
    assert asv_dir.is_dir()
    assert (asv_dir / "index.html").is_file()


def test_cli_gen_jobs(benchmark_script_path, tmp_path, lttng_ust_repo):
    output = tmp_path / "output"
    commits = ["A1", "B1", "C1", "D1"]
    args = [
        str(benchmark_script_path),
        "--repo-path",
        str(lttng_ust_repo),
        "generate-jobs",
        "--dry-run",
        "--commits",
        ",".join(commits),
    ]

    p = subprocess.Popen(args, stdout=open(output, "w"))
    p.wait()
    assert p.returncode == 0

    with open(output, "r") as f:
        job = yaml.load(f, yaml.SafeLoader)

    job_commits = job["environment"]["COMMITS"].split(" ")
    assert len(job_commits) == len(commits)
    for commit in commits:
        assert commit in job_commits


def test_cli_gen_jobs_tags_only(benchmark_script_path, tmp_path, lttng_ust_repo):
    output = tmp_path / "output"
    commits = [
        "67ceba204e9a5bb616f45142acfc5d19812821a3",
        "45262bfa8e4f60aa286a6dfef2f09fba9c7d9afa",
        "13861e2d626f103b1ab5ded862e0b9f155538682",
        "de624c20694f69702b42c5d47b5bcf692293a238",
        "5a8c530cec95b827a4840c0d032b502f82f0dde3",
        "04b0e69420e865e56dba55bd09621cb6dc61ec78",
        "0d498e120478f62cbac4fae7125b17a3c8a38d06",
        "94d13921f67a05ace5b39713ef65cc1f4e9ef1c0",
        "299e6bca8ec920c6e8cb9d853ad4fd7733bf33e9",
        "c8cd63c2f1cfffd9a274abdb9321186584c79dcd",
        "0bd56396d5aea100aadc9c7e030c2ffd15b81d9d",
        "5ad3afb17fd68bbf3038687a3e27674f30c159dd",
        "83d51a7498a113adc2c124e502edfa717564f630",
    ]
    args = [
        str(benchmark_script_path),
        "--repo-path",
        str(lttng_ust_repo),
        "--branches",
        "stable-2.13:06f280fd4452f88ce67e622c4961e11ad376f469",
        "generate-jobs",
        "--batch-size",
        "0",
        "--force",
        "--dry-run",
        "--tags-only",
    ]

    p = subprocess.Popen(args, stdout=open(output, "w"))
    p.wait()
    assert p.returncode == 0

    with open(output, "r") as f:
        job = yaml.load(f, yaml.SafeLoader)

    job_commits = job["environment"]["COMMITS"].split(" ")
    assert len(job_commits) == len(commits)
    for commit in commits:
        assert commit in job_commits


def test_cli_gen_jobs_regression(benchmark_script_path, tmp_path, lttng_ust_repo):
    output = tmp_path / "output"
    commits = [
        "0c8cb8ea5394f057e15bcc033efa468a8f0b0f55",
        "2369c956dc343b177103d2ec076be0c3ccece444",
    ]
    args = [
        str(benchmark_script_path),
        "--repo-path",
        str(lttng_ust_repo),
        "generate-jobs",
        "--force",
        "--dry-run",
        "--regression",
        "--commits",
        "v2.14.0",
    ]

    p = subprocess.Popen(args, stdout=open(output, "w"))
    p.wait()
    assert p.returncode == 0

    with open(output, "r") as f:
        job = yaml.load(f, yaml.SafeLoader)

    job_commits = job["environment"]["COMMITS"].split(" ")
    assert len(job_commits) > 0
    for commit in commits:
        assert commit in job_commits


@pytest.mark.parametrize(
    "benchmark,returncode",
    [
        ("basic.tracing_enabled.ns_per_event", 0),
        ("basic.tracing_enabled.start_time", 1),
    ],
)
def test_cli_regression(
    benchmark_script_path, tmp_path, lttng_ust_repo, benchmark, returncode
):
    output = tmp_path / "output"
    data_files = [
        pathlib.Path(__file__).parents[0]
        / "data"
        / "lttng-ust-benchmarks"
        / "2.13.10.json",
        pathlib.Path(__file__).parents[0]
        / "data"
        / "lttng-ust-benchmarks"
        / "2.13.0.json",
    ]
    args = [
        str(benchmark_script_path),
        "--repo-path",
        str(lttng_ust_repo),
        "regression",
        "-b",
        benchmark,
    ]
    for data_file in data_files:
        args.extend(["-i", str(data_file)])

    p = subprocess.Popen(args, stdout=open(output, "w"))
    p.wait()
    assert p.returncode == returncode
