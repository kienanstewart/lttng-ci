# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-License-Identifier: AGPL-3.0-only
#

import pydantic
import sqlmodel

from . import data


class FileRunLink(sqlmodel.SQLModel, table=True):
    run_id: int | None = sqlmodel.Field(
        default=None, primary_key=True, foreign_key="run.id", ondelete="CASCADE"
    )
    file_id: int | None = sqlmodel.Field(
        default=None, primary_key=True, foreign_key="file.id", ondelete="CASCADE"
    )


class Run(sqlmodel.SQLModel, table=True):
    id: int | None = sqlmodel.Field(default=None, primary_key=True)
    project: str = sqlmodel.Field(index=True)
    job: str = sqlmodel.Field(index=True)
    run: int = sqlmodel.Field(index=True)
    state: data.RunState = sqlmodel.Field(index=True)
    # @TODO: arch, conf, build,

    # Relationships
    stages: list["RunStage"] = sqlmodel.Relationship(back_populates="run")
    test_results: list["TestResults"] = sqlmodel.Relationship(back_populates="run")
    files: list["File"] = sqlmodel.Relationship(
        back_populates="runs",
        link_model=FileRunLink,
    )


class RunStage(sqlmodel.SQLModel, table=True):
    run_id: int = sqlmodel.Field(
        index=True, foreign_key="run.id", primary_key=True, ondelete="CASCADE"
    )
    before: int | None
    stage: data.RunStage = sqlmodel.Field(primary_key=True)
    state: data.RunState

    # Relationships
    run: Run = sqlmodel.Relationship(back_populates="stages")


class TestResults(sqlmodel.SQLModel, table=True):
    """
    run_id + name are not considered unique since duplicate results are normal
    for tests that are repeated (e.g., checking for flakiness within a testcase
    """

    id: int | None = sqlmodel.Field(primary_key=True)
    run_id: int = sqlmodel.Field(index=True, foreign_key="run.id", ondelete="CASCADE")
    test_name: str = sqlmodel.Field(index=True)
    state: data.TestState
    description: str | None

    # Relationships
    run: Run = sqlmodel.Relationship(back_populates="test_results")


class File(sqlmodel.SQLModel, table=True):
    id: int | None = sqlmodel.Field(default=None, primary_key=True)
    path: str = sqlmodel.Field()
    description: str | None = sqlmodel.Field(default=None)
    content_type: str = sqlmodel.Field(default="text/plain")

    # Relationships
    runs: list["Run"] = sqlmodel.Relationship(
        back_populates="files", link_model=FileRunLink
    )


class FileModel(pydantic.BaseModel):
    name: str
    content: str
    description: str
    content_type: str


class AddFilesModel(pydantic.BaseModel):
    run_id: int
    files: list[FileModel]


class AddTestModel(pydantic.BaseModel):
    run_id: int
    content: str
    test_format: data.TestFormat
    test_prefix: str | None = None
