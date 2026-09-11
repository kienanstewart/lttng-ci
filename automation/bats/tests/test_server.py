#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-LicenseIdentifier: AGPL-3.0-only
#

import json
import logging
import pathlib

import fastapi.testclient
from fixtures import app_and_conf, file_json, test_data_dir


def test_add_run(app_and_conf, test_data_dir):
    app, conf = app_and_conf
    with open(test_data_dir / "run.json") as f:
        run = json.load(f)

    with fastapi.testclient.TestClient(app) as client:
        response = client.post("/api/v0/run", json=run)
        assert response.status_code == 200
        assert response.json()["id"] >= 1


def test_add_duplicate_run(app_and_conf, test_data_dir):
    app, conf = app_and_conf
    with open(test_data_dir / "run.json") as f:
        run = json.load(f)

    with fastapi.testclient.TestClient(app) as client:
        response = client.post("/api/v0/run", json=run)
        assert response.status_code == 200

        # It's okay to add a duplicate run where the id isn't set
        response = client.post("/api/v0/run", json=run)
        assert response.status_code == 200

        # A duplicate run where the id already exists isn't permitted
        run["id"] = 1
        response = client.post("/api/v0/run", json=run)
        assert response.status_code != 200
        assert "detail" in response.json()

        # A duplicate run where the id doesn't already exist is fine, I guess.
        run["id"] = 3
        response = client.post("/api/v0/run", json=run)
        assert response.status_code == 200
        assert response.json()["id"] == 3


def test_add_run_files_no_run(app_and_conf, file_json):
    app, conf = app_and_conf

    with fastapi.testclient.TestClient(app) as client:
        response = client.post("/api/v0/run/add_files", json=file_json)
        assert response.status_code != 200
        assert "detail" in response.json()


def test_add_run_files(app_and_conf, test_data_dir, file_json):
    app, conf = app_and_conf
    with open(test_data_dir / "run.json") as f:
        run = json.load(f)

    with fastapi.testclient.TestClient(app) as client:
        response = client.post("/api/v0/run", json=run)
        assert response.status_code == 200
        run = response.json()

        file_json["run_id"] = run["id"]
        response = client.post("/api/v0/run/add_files", json=file_json)
        assert response.status_code == 200

        files = response.json()
        assert type(files) is list
        assert len(files) == 2
        for x in files:
            assert type(x) is dict

        # Storage path /run/run.id/name
        for entry in file_json["files"]:
            expected = (
                pathlib.Path(conf["storage_path"])
                / "run"
                / str(run["id"])
                / entry["name"]
            )
            assert expected.is_file()
            # If content contains control characters, we need to account for their
            # encoded size not just the length of the string.
            assert expected.stat().st_size == len(entry["content"].encode())

            with open(expected) as f:
                content = f.read()

            assert content == entry["content"]


def test_add_run_stage_no_run(app_and_conf, test_data_dir):
    app, conf = app_and_conf
    with open(test_data_dir / "run.json") as f:
        run = json.load(f)

    with open(test_data_dir / "stage.json") as f:
        stage = json.load(f)

    with fastapi.testclient.TestClient(app) as client:
        response = client.post("/api/v0/run/add_stage", json=stage)
        assert response.status_code != 200
        assert "detail" in response.json()


def test_add_run_stage(app_and_conf, test_data_dir):
    app, conf = app_and_conf
    with open(test_data_dir / "run.json") as f:
        run = json.load(f)

    with open(test_data_dir / "stage.json") as f:
        stage = json.load(f)

    with fastapi.testclient.TestClient(app) as client:
        response = client.post("/api/v0/run", json=run)
        assert response.status_code == 200
        run = response.json()

        stage["run_id"] = run["id"]
        response = client.post("/api/v0/run/add_stage", json=stage)
        assert response.status_code == 200


def test_add_run_duplicate_stage(app_and_conf, test_data_dir):
    app, conf = app_and_conf
    with open(test_data_dir / "run.json") as f:
        run = json.load(f)

    with open(test_data_dir / "stage.json") as f:
        stage = json.load(f)

    with fastapi.testclient.TestClient(app) as client:
        response = client.post("/api/v0/run", json=run)
        assert response.status_code == 200
        run = response.json()

        stage["run_id"] = run["id"]
        response = client.post("/api/v0/run/add_stage", json=stage)
        assert response.status_code == 200

        response = client.post("/api/v0/run/add_stage", json=stage)
        assert response.status_code != 200


def test_add_run_tests_junit_no_run(app_and_conf, test_data_dir):
    app, conf = app_and_conf
    with open(test_data_dir / "test_results.junit.json") as f:
        tap = json.load(f)

    with fastapi.testclient.TestClient(app) as client:
        response = client.post("/api/v0/run/add_tests", json=tap)
        assert response.status_code != 200
        assert "detail" in response.json()


def test_add_run_tests_junit(app_and_conf, test_data_dir):
    app, conf = app_and_conf
    with open(test_data_dir / "run.json") as f:
        run = json.load(f)

    with open(test_data_dir / "test_results.junit.json") as f:
        junit = json.load(f)

    with fastapi.testclient.TestClient(app) as client:
        response = client.post("/api/v0/run", json=run)
        assert response.status_code == 200
        run = response.json()

        junit["run_id"] = run["id"]
        response = client.post("/api/v0/run/add_tests", json=junit)
        assert response.status_code == 200
        tests = response.json()

        assert len(tests) == 243


def test_add_run_tests_tap_no_run(app_and_conf, test_data_dir):
    app, conf = app_and_conf
    with open(test_data_dir / "test_results.tap.json") as f:
        tap = json.load(f)

    with fastapi.testclient.TestClient(app) as client:
        response = client.post("/api/v0/run/add_tests", json=tap)
        assert response.status_code != 200
        assert "detail" in response.json()


def test_add_run_tests_tap(app_and_conf, test_data_dir):
    app, conf = app_and_conf
    with open(test_data_dir / "run.json") as f:
        run = json.load(f)

    with open(test_data_dir / "test_results.tap.json") as f:
        tap = json.load(f)

    with fastapi.testclient.TestClient(app) as client:
        response = client.post("/api/v0/run", json=run)
        assert response.status_code == 200
        run = response.json()

        tap["run_id"] = run["id"]
        response = client.post("/api/v0/run/add_tests", json=tap)
        assert response.status_code == 200
        tests = response.json()
        assert len(tests) == 10
        assert tests[4]["state"] == "pass"
        assert tests[5]["state"] == "fail"
        assert tests[6]["state"] == "skip"
        assert tests[7]["state"] == "xfail"
        assert tests[8]["state"] == "xpass"
        assert tests[9]["state"] == "skip"
