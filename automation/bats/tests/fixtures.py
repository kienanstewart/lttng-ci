#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-LicenseIdentifier: AGPL-3.0-only
#

import json
import os
import pathlib
import sys

import fastapi.testclient
import pytest

# Add package root
sys.path.append(str((pathlib.Path(__file__) / "..").absolute()))


@pytest.fixture
def app_and_conf(tmpdir):
    from bats.server import app, conf

    conf["db_url"] = "sqlite:///" + str(tmpdir / "db.sql")
    conf["storage_path"] = str(tmpdir / "data")
    yield app, conf


@pytest.fixture(scope="session")
def test_data_dir():
    yield (pathlib.Path(__file__).parents[0] / "data").absolute()


@pytest.fixture
def file_json(test_data_dir):
    with open(test_data_dir / "run_files.json") as f:
        files = json.load(f)

    with open(test_data_dir / "console.log") as f:
        files["files"][0]["content"] = f.read()

    with open(test_data_dir / "example.xml") as f:
        files["files"][1]["content"] = f.read()

    yield files
