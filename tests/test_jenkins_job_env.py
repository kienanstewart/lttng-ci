#!/usr/bin/env python3
#
# SPDX-License-Identifier: GPL-2.0-only
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
#

import http.server
import pathlib
import subprocess

import pytest
import pytest_httpserver


def archive_basic():
    return pathlib.Path(__file__).parents[0] / "data" / "archive.zip"


def run_jenkins_job_env(args=list(), output_path=None):
    script = pathlib.Path(__file__).parents[1] / "scripts" / "jenkins_job_env.py"
    cmd_args = [script] + args
    stdout = subprocess.PIPE
    stderr = subprocess.PIPE
    if output_path is not None:
        stdout = open(output_path / "stdout", "w")
        stderr = open(output_path / "stderr", "w")

    return (
        subprocess.Popen(cmd_args, stdout=stdout, stderr=stderr),
        output_path / "stdout" if output_path is not None else None,
        output_path / "stderr" if output_path is not None else None,
    )


def test_noargs_fails(tmp_path):
    p, stdout, stderr = run_jenkins_job_env(["fetch"], None)
    p.wait()
    assert p.returncode != 0


def test_fetch_local_file(tmp_path_factory):
    # Usage: fetch -f path_to.zip [<dir>]
    output_dir = tmp_path_factory.mktemp("output")
    p, stdout, stderr = run_jenkins_job_env(
        ["fetch", "-f", archive_basic(), output_dir / "output"], output_dir
    )
    p.wait()
    assert p.returncode == 0
    assert (
        output_dir / "output" / "archive" / "src" / "lttng-tools" / "README.md"
    ).is_file()
    assert (output_dir / "output" / "deactivate").is_file()
    assert (output_dir / "output" / "activate").is_file()


def test_fetch_http(tmp_path_factory, httpserver: pytest_httpserver.HTTPServer):
    # Usage: fetch -u http://....zip [<dir>]
    with open(archive_basic(), "rb") as f:
        content = f.read()

    httpserver.expect_request("/archive.zip").respond_with_data(
        content, content_type="application/zip"
    )
    output_dir = tmp_path_factory.mktemp("output")
    p, stdout, stderr = run_jenkins_job_env(
        ["fetch", "-u", httpserver.url_for("/archive.zip"), output_dir / "output"],
        output_dir,
    )
    p.wait()
    assert p.returncode == 0
    assert (
        output_dir / "output" / "archive" / "src" / "lttng-tools" / "README.md"
    ).is_file()
    assert (output_dir / "output" / "deactivate").is_file()
    assert (output_dir / "output" / "activate").is_file()


def test_fetch_http_by_job_spec(
    tmp_path_factory, httpserver: pytest_httpserver.HTTPServer
):
    # Usage: fetch -s http://host -j X [-jc Y] -b N [<dir>]
    job = "dev_review_fake"
    jc = "build=std,conf=std"
    build = 161
    with open(archive_basic(), "rb") as f:
        content = f.read()

    httpserver.expect_request(
        f"/job/{job}/{jc}/{build}/artifact/*zip*/archive.zip"
    ).respond_with_data(content, content_type="application/zip")
    output_dir = tmp_path_factory.mktemp("output")
    p, stdout, stderr = run_jenkins_job_env(
        [
            "fetch",
            "-s",
            httpserver.url_for("/"),
            "-j",
            job,
            "-jc",
            jc,
            "-b",
            str(build),
            output_dir / "output",
        ],
        output_dir,
    )
    p.wait()
    assert p.returncode == 0
    assert (
        output_dir / "output" / "archive" / "src" / "lttng-tools" / "README.md"
    ).is_file()
    assert (output_dir / "output" / "deactivate").is_file()
    assert (output_dir / "output" / "activate").is_file()
