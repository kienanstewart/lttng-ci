#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-LicenseIdentifier: AGPL-3.0-only
#

import os
import pathlib
import stat

import fastapi.testclient
import pytest
from fixtures import app_and_conf


def test_hello(app_and_conf):
    app, conf = app_and_conf
    with fastapi.testclient.TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"message": "Hello"}

    storage_path = pathlib.Path(conf["storage_path"])
    assert storage_path.is_dir()

    db = pathlib.Path(conf["db_url"].removeprefix("sqlite:///"))
    assert db.is_file()


def test_cannot_create_database_file(app_and_conf):
    app, conf = app_and_conf
    conf["db_url"] = "sqlite:////fake/fake/fake/fake"
    with pytest.raises(Exception):
        with fastapi.testclient.TestClient(app) as client:
            pass


def test_unwriteable_database_file(app_and_conf):
    app, conf = app_and_conf
    db = pathlib.Path(conf["db_url"].removeprefix("sqlite:///"))
    db.touch()
    os.chmod(db, stat.S_IREAD)
    with pytest.raises(Exception):
        with fastapi.testclient.TestClient(app) as client:
            pass

    db.unlink()


def test_cannot_create_data_folder(app_and_conf):
    app, conf = app_and_conf
    conf["storage_path"] = "/fake/fake/fake/fake"
    with pytest.raises(Exception):
        with fastapi.testclient.TestClient(app) as client:
            pass


def test_unwriteable_data_folder(app_and_conf):
    app, conf = app_and_conf
    os.mkdir(conf["storage_path"])
    os.chmod(conf["storage_path"], stat.S_IREAD)

    with pytest.raises(Exception):
        with fastapi.testclient.TestClient(app) as client:
            pass

    os.rmdir(conf["storage_path"])
