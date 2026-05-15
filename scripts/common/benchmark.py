#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-License-Identifier: GPL-2.0-only
#

import enum


class BenchmarkState(enum.Enum):
    BUILD_FAILURE = -1
    COMPLETE = 0
    CONTAINS_RUN_FAILURES = 1
    MISSING_BENCHMARK_RESULTS = 2
