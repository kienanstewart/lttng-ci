# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-License-Identifier: GPL-2.0-only
#

import pathlib
import sys
import subprocess

import pytest
import pytest_httpserver

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "lib" / "resources"))

import bats_upload


@pytest.fixture(scope="session")
def bats_script_path():
    yield pathlib.Path(__file__).parents[1] / "lib" / "resources" / "bats_upload.py"


@pytest.fixture
def bats_test_data(job_status):
    archive_path = pathlib.Path(__file__).parents[0] / "data" / "bats_upload"
    state_path = archive_path / "state_{}.json".format(job_status)
    console_log_path = archive_path / "console.log"
    yield state_path, archive_path, console_log_path


def setup_httpserver_expectations(httpserver, include_console: bool = False):
    expected_request_count = 3
    httpserver.expect_ordered_request("/api/v0/run", method="POST").respond_with_json(
        {"id": 1}
    )
    if include_console:
        expected_request_count += 1
        httpserver.expect_ordered_request(
            "/api/v0/run/add_files", method="POST"
        ).respond_with_json({})

    # XML
    httpserver.expect_ordered_request(
        "/api/v0/run/add_tests", method="POST"
    ).respond_with_json(list())

    # TAP
    httpserver.expect_ordered_request(
        "/api/v0/run/add_tests", method="POST"
    ).respond_with_json(list())

    return expected_request_count


@pytest.mark.parametrize(["job_status"], [("SUCCESS",), ("FAILURE",)])
def test_upload_cli(
    job_status,
    bats_script_path,
    bats_test_data,
    httpserver: pytest.httpserver.HTTPServer,
):
    state_path, archive_path, console_log_path = bats_test_data
    expected_request_count = setup_httpserver_expectations(
        httpserver, job_status != "SUCCESS"
    )
    p = subprocess.Popen(
        [
            str(bats_script_path),
            "-v",
            "--state-file",
            str(state_path),
            "--console-log",
            str(console_log_path),
            "--artifact-directory",
            str(archive_path),
            "--server",
            httpserver.url_for("/"),
        ]
    )
    p.wait()
    httpserver.check()
    assert len(httpserver.log) == expected_request_count
    assert p.returncode == 0


@pytest.mark.parametrize(["job_status"], [("SUCCESS",), ("FAILURE",)])
def test_upload_cli_env(
    job_status,
    bats_script_path,
    bats_test_data,
    httpserver: pytest.httpserver.HTTPServer,
    monkeypatch,
):
    state_path, archive_path, console_log_path = bats_test_data
    expected_request_count = setup_httpserver_expectations(
        httpserver, job_status != "SUCCESS"
    )
    monkeypatch.setenv("BATS_JOB_STATE_FILE", str(state_path))
    monkeypatch.setenv("BATS_JOB_CONSOLE_LOG", str(console_log_path))
    monkeypatch.setenv("BATS_JOB_ARTIFACT_DIRECTORY", str(archive_path))
    monkeypatch.setenv("BATS_SERVER", httpserver.url_for("/"))
    p = subprocess.Popen(
        [
            str(bats_script_path),
            "-v",
        ]
    )
    p.wait()
    httpserver.check()
    assert len(httpserver.log) == expected_request_count
    assert p.returncode == 0


@pytest.mark.parametrize(["job_status"], [("SUCCESS",), ("FAILURE",)])
def test_upload_job(
    job_status, bats_test_data, httpserver: pytest.httpserver.HTTPServer
):
    state_path, archive_path, console_log_path = bats_test_data
    expected_request_count = setup_httpserver_expectations(
        httpserver, job_status != "SUCCESS"
    )
    bats_upload.main(
        httpserver.url_for("/"), state_path, console_log_path, archive_path
    )
    httpserver.check()
    assert len(httpserver.log) == expected_request_count
