#!/bin/bash
#
# SPDX-FileCopyrightText: 2025 Kienan Stewart <kstewart@efficios.com>
# SPDX-License-Identifier: GPL-2.0-only

# This file should be used as a jenkins job builder RAW import allowing the
# override of the "build" variable on shell builder execution.

set -exu

# shellcheck disable=SC2034
conf=agents
