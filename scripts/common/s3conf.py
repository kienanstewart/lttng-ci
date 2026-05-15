#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-License-Identifier: GPL-2.0-only

import os

# Get S3 config from environment
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", os.getenv("S3_KEY_USR"))
S3_ANONYMOUS_URL = os.getenv(
    "S3_HTTP_BUCKET_URL", "https://obj-lava.internal.efficios.com"
)
S3_BASE_DIR = os.getenv("S3_BASE_DIR", "system-tests")
S3_BUCKET = os.getenv("S3_BUCKET", "lava")
S3_HOST = os.getenv("S3_HOST", "obj.internal.efficios.com")
S3_HTTP_BUCKET_URL = S3_ANONYMOUS_URL
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", os.getenv("S3_KEY_PSW"))
S3_STORAGE_PATH = None
