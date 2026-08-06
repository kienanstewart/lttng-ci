#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-LicenseIdentifier: GPL-2.0-only
#
"""
Glue script to upload job result state from Jenkins post-build to BATS
"""

import argparse
import json
import logging
import os
import pathlib
import sys
import urllib.request

from typing import Optional


def _get_parser():
    parser = argparse.ArgumentParser(prog="bats_upload.py")
    parser.set_defaults(log_level=logging.INFO)
    parser.add_argument(
        "-v", "--verbose", action="store_const", dest="log_level", const=logging.DEBUG
    )
    parser.add_argument(
        "-q", "--quiet", action="store_const", dest="log_level", const=logging.WARNING
    )

    parser.add_argument(
        "--state-file",
        action="store",
        type=pathlib.Path,
        default=os.environ.get("BATS_JOB_STATE_FILE", None),
    )
    parser.add_argument(
        "--console-log",
        action="store",
        type=pathlib.Path,
        default=os.environ.get("BATS_JOB_CONSOLE_LOG", None),
    )
    parser.add_argument(
        "--artifact-directory",
        action="store",
        type=pathlib.Path,
        default=os.environ.get("BATS_JOB_ARTIFACT_DIRECTORY", None),
    )
    parser.add_argument(
        "-s", "--server", action="store", default=os.environ.get("BATS_SERVER", None)
    )
    return parser


def _request(server, endpoint, data=None):
    encoded_data = None
    if data is not None:
        encoded_data = json.dumps(data).encode("utf-8")

    req = urllib.request.Request("{}/{}".format(server, endpoint), data=encoded_data)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        if resp.status != 200:
            raise RuntimeError("Unexpected response status: {}".format(resp.status))

        return json.loads(resp.read())


def main(
    bats_server: str,
    state_file: pathlib.Path,
    console_log: Optional[pathlib.Path] = None,
    artifact_directory: Optional[pathlib.Path] = None,
):
    with open(state_file, "r") as f:
        state = json.load(f)

    data = {
        "run": state["run"],
        "project": state["environment"].get("PROJECT_NAME", "unknown"),
        "job": state["job"],
        "state": state["result"].lower(),
    }

    result = _request(bats_server, "api/v0/run", data)
    run_id = result["id"]
    logging.info("Received run id: {}".format(run_id))
    if state["result"] != "SUCCESS" and console_log:
        logging.info("Uploading console log '{}'".format(str(console_log)))
        with open(str(console_log), "r") as f:
            data = {
                "run_id": run_id,
                "files": [
                    {
                        "name": "console.log",
                        "description": "Run console log",
                        "content": f.read(),
                        "content_type": "text/plain",
                    }
                ],
            }

        _request(bats_server, "api/v0/run/add_files", data)

    # Identify and upload test results
    if artifact_directory and artifact_directory.is_dir():
        # Assume .xml are junit
        for item in artifact_directory.glob("**/*.xml"):
            with open(item, "r") as f:
                data = {
                    "run_id": run_id,
                    "test_format": "junit",
                    "test_prefix": "",
                    "content": f.read(),
                }

            _request(bats_server, "api/v0/run/add_tests", data)

        # Assume tap/**/*.log are tap results
        for item in artifact_directory.glob("tap/**/*.log"):
            prefix = (
                str(item.relative_to(artifact_directory / "tap"))
                .rstrip(".log")
                .replace("/", ".")
            )
            with open(item, "r") as f:
                data = {
                    "run_id": run_id,
                    "test_format": "tap",
                    "test_prefix": prefix,
                    "content": f.read(),
                }

            _request(bats_server, "api/v0/run/add_tests", data)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = _get_parser()
    args = parser.parse_args()
    logging.getLogger().setLevel(args.log_level)
    try:
        main(args.server, args.state_file, args.console_log, args.artifact_directory)
    except:
        logging.exception("Unhandled exception")
        sys.exit(-1)
