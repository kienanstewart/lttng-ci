#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-License-Identifier: AGPL-3.0-only
#

import argparse
import contextlib
import logging
import os
import pathlib
import sys
from typing import Annotated

import fastapi
import junitparser
import pydantic
import sqlalchemy
import sqlmodel
import tap
import tap.parser
import yaml

from . import data
from .models import *


class Conf(dict):

    def set_defaults(self):
        self["db_url"] = "sqlite:///database.db"
        self["storage_path"] = str(pathlib.Path("data").absolute())


@contextlib.asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    global engine

    logging.debug("Connecting to DB at '{}'".format(conf["db_url"]))
    engine = sqlmodel.create_engine(
        conf["db_url"],
        connect_args={"check_same_thread": False},
    )
    sqlmodel.SQLModel.metadata.create_all(engine)

    storage_path = pathlib.Path(conf["storage_path"])
    if not storage_path.exists():
        storage_path.mkdir()

    if not storage_path.is_dir():
        raise Exception("Storage path '{}' is not a directory".format(storage_path))

    if not os.access(storage_path, os.W_OK):
        raise Exception("Storage path '{}' is not writable".format(storage_path))

    # @TODO: Run necessary data migrations?
    # FastAPI seems to suggest Alembic https://alembic.sqlalchemy.org/en/latest/autogenerate.html
    #
    yield
    # Teardown


conf = Conf()
conf.set_defaults()
app = fastapi.FastAPI(lifespan=lifespan)
engine = None


def get_session():
    global engine

    with sqlmodel.Session(engine) as session:
        yield session


@app.get("/")
async def root():
    return {"message": "Hello"}


@app.get("/api/v0/run/{id}")
async def read_run(
    id: int, session: Annotated[sqlmodel.Session, fastapi.Depends(get_session)]
):
    run = session.get(Run, id)
    if not run:
        raise fastapi.HTTPException(status_code=404, detail="Run not found")

    return run


@app.post("/api/v0/run")
async def create_run(
    run: Run, session: Annotated[sqlmodel.Session, fastapi.Depends(get_session)]
):
    if run.id and session.get(Run, run.id) is not None:
        raise fastapi.HTTPException(
            status_code=400, detail="Run id '{}' already exists".format(run.id)
        )

    session.add(run)
    session.commit()
    return session.get(Run, run.id)


@app.post("/api/v0/run/add_files")
async def add_run_files(
    add_data: AddFilesModel,
    session: Annotated[sqlmodel.Session, fastapi.Depends(get_session)],
):
    # @TODO Use a depends instead
    global conf

    run = session.get(Run, add_data.run_id)
    if not run:
        raise fastapi.HTTPException(
            status_code=404, detail="Run '{}' not found".format(add_data.run_id)
        )

    file_ids = list()
    ret = list()
    rollback_delete = list()
    storage_dir = (pathlib.Path(conf["storage_path"]) / "run" / str(run.id)).absolute()
    storage_dir.mkdir(parents=True, exist_ok=True)
    try:
        for file_model in add_data.files:
            # Set a default path
            path = storage_dir / file_model.name

            # Validate that name doesn't contain path characters
            if path.absolute() != path or path.absolute().parent != storage_dir:
                raise fastapi.HTTPException(
                    status_code=400,
                    detail="Invalid path '{}': contains links or directory crossings".format(
                        path
                    ),
                )

            if path.exists():
                raise fastapi.HTTPException(
                    status_code=400,
                    detail="File '{}' already exists in storage for run '{}'".format(
                        file_model.name, run.id
                    ),
                )

            # Write the file
            try:
                with open(path, "w") as f:
                    logging.info("Writing '{}'".format(path))
                    f.write(file_model.content)
            except Exception as e:
                logging.exception(
                    "Failed to write file '{}' during upload".format(path)
                )
                raise fastapi.HTTPException(
                    status_code=400,
                    detail="Failed to write file '{}': {}".format(file_model.name, e),
                )

            rollback_delete.append(path)

            # Add a File model to insert
            f = File(
                id=None,
                path=str(path.relative_to((pathlib.Path(conf["storage_path"])))),
                description=file_model.description,
                content_type=file_model.content_type,
            )
            # Note: using add_all seems to cause sqlalchemy to lose track of
            # the object association, so the commits are done on at a time.
            session.add(f)
            session.commit()
            session.refresh(f)
            file_ids.append(f.id)

    except Exception as e:
        logging.exception("Rolling back file upload due to exception: {}".format(e))
        for f in files_ids:
            statement = sqlmodel.select(File).where(File.id == f)
            _file = session.exec(statement).first()
            _file.delete()
            try:
                session.commit()
            except Exception as e:
                logging.exception(
                    "Exception during rollback of file id={}: {}".format(f, e)
                )

        for f in rollback_delete:
            try:
                f.unlink()
            except Exception as e:
                logging.exception(
                    "Exception ignored while deleting file '{}' during rollback: {}".format(
                        f, e
                    )
                )

        raise e

    files = list()
    statement = sqlmodel.select(File).where(sqlmodel.col(File.id).in_(file_ids))
    for f in session.exec(statement).all():
        files.append(f)

    return files


@app.post("/api/v0/run/add_tests")
async def add_run_tests(
    add_data: AddTestModel,
    session: Annotated[sqlmodel.Session, fastapi.Depends(get_session)],
):
    run = session.get(Run, add_data.run_id)
    if not run:
        raise fastapi.HTTPException(
            status_code=404, detail="Run '{}' not found".format(add_data.run_id)
        )

    tests = list()
    if add_data.test_format == data.TestFormat.TAP:
        parser = tap.parser.Parser()
        for tap_line in parser.parse_text(add_data.content):
            if type(tap_line) is not tap.line.Result:
                continue

            test_state = data.TestState.PASS if tap_line.ok else data.TestState.FAIL
            if tap_line.skip:
                test_state = data.TestState.SKIP

            if tap_line.todo:
                # in TAP, a todo is not expected to pass
                # a passing todo is unexpected, and will be flagged as XPASS
                test_state = (
                    data.TestState.XPASS if tap_line.ok else data.TestState.XFAIL
                )

            tests.append(
                TestResults(
                    run_id=add_data.run_id,
                    test_name=(
                        add_data.test_prefix + ".{}".format(tap_line.number)
                        if add_data.test_prefix
                        else str(tap_line.number)
                    ),
                    state=test_state,
                    description=tap_line.description.lstrip("- "),
                )
            )

    elif add_data.test_format == data.TestFormat.JUNIT:
        results = junitparser.JUnitXml.fromstring(add_data.content)
        for test_suite in results:
            # A suite.name might be 'pytest' for example
            # Arguable, the name could be
            #   "{suite.name}.{test_case.classname}.{test_case.name}"
            for test_case in test_suite:
                test_name = "{}.{}".format(test_case.classname, test_case.name)
                test_state = None
                if test_case.is_skipped:
                    test_state = data.TestState.SKIP
                    # If we want to distingish xfail/xpass, the
                    # pytest -> junit sets additional result elements
                    for element in test_case.result:
                        if element.type == "pytest.xfail":
                            test_state = data.TestState.XFAIL
                        elif element.type == "pytest.xpass":
                            test_state = data.TestState.XPASS
                elif test_case.is_failure:
                    test_state = data.TestState.FAIL
                elif test_case.is_passed:
                    test_state = data.TestState.PASS

                tests.append(
                    TestResults(
                        run_id=add_data.run_id,
                        test_name=(
                            add_data.prefix + ".{}".format(test_name)
                            if add_data.test_prefix
                            else test_name
                        ),
                        state=test_state,
                        description="",
                    )
                )

    else:
        raise fastapi.HTTPException(
            status_code=400,
            detail="Unsupported test format: {}".format(add_data.test_format),
        )

    for test in tests:
        session.add(test)

    try:
        session.commit()
    except sqlalchemy.exc.IntegrityError as e:
        raise fastapi.HTTPException(
            status_code=400, detail="Duplicate data: {}".format(e)
        )

    for test in tests:
        session.refresh(test)

    return tests


@app.post("/api/v0/run/add_stage")
async def create_run_stage(
    run_stage: RunStage,
    session: Annotated[sqlmodel.Session, fastapi.Depends(get_session)],
):
    run = session.get(Run, run_stage.run_id)
    if not run:
        raise fastapi.HTTPException(
            status_code=400, detail="Run '{}' not found".format(run_stage.run_id)
        )

    try:
        session.add(run_stage)
        session.commit()
    except sqlalchemy.exc.IntegrityError as e:
        raise fastapi.HTTPException(status_code=400, detail=str(e))

    session.refresh(run_stage)
    return run_stage


def main(argv):
    global conf

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        prog="server", description="Build Analysis Tracker server"
    )
    parser.add_argument("-c", "--config", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)
    if args.config is not None:
        with open(args.config, "r") as f:
            logging.info("Loading configuration from '{}'".format(args.config))
            conf.update(yaml.safe_load(f))

    logging.debug("Configuration: {}".format(conf))


if __name__ == "__main__":
    main(sys.argv[1:])
