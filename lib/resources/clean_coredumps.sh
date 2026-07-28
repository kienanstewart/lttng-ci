#!/bin/bash
#
# SPDX-License-Identifier: GPL-2.0-only
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
#

find "/tmp" -name "core\.[0-9]*" -type f -delete || true
