#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-License-Identifier: AGPL-3.0-only
#

import enum


class TestFormat(str, enum.Enum):
    """
    Supported test formats
    """

    TAP = "tap"
    JUNIT = "junit"


class RunState(str, enum.Enum):
    """
    Representation of the CI run's state.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    UNSTABLE = "warning"
    WARNING = "warning"


class TestState(str, enum.Enum):
    """
    Representation of an individual test's state.
    """

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    XFAIL = "xfail"
    XPASS = "xpass"


class RunStage(str, enum.Enum):
    """
    Representation of the stages of runs in a general sense.
    """

    CHECKOUT = "checkout"
    DEPENDENCIES = "deps"
    CONFIGURE = "configure"
    BUILD = "build"
    TEST = "test"
    # were there coredumps, did the test results parse, did publishing succeed, etc.?
    POSTBUILD = "postbuild"
