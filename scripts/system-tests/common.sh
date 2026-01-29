#!/bin/bash
# SPDX-FileCopyrightText: 2025 Kienan Stewart <kstewart@efficios.com>
# SPDX-License-Identifier: GPL-3.0-or-later

create_s3_config() {
    export S3_KERNEL_MODULE_SYMVERS=$S3_BUCKET/$S3_BASE_DIR/kernel/$KERNEL_COMMIT_ID.$BUILD_DEVICE.symvers
    export S3_KERNEL_CONFIG=$S3_BUCKET/$S3_BASE_DIR/kernel/$KERNEL_COMMIT_ID.$BUILD_DEVICE.config
    export S3_KERNEL_IMAGE=$S3_BUCKET/$S3_BASE_DIR/kernel/$KERNEL_COMMIT_ID.$BUILD_DEVICE.bzImage
    export S3_LINUX_MODULES=$S3_BUCKET/$S3_BASE_DIR/modules/$KERNEL_COMMIT_ID.$BUILD_DEVICE.linux.modules.tar.xz
    export S3_LTTNG_MODULES=$S3_BUCKET/$S3_BASE_DIR/modules/$BUILD_NAME.$BUILD_DEVICE.lttng.modules.tar.xz

    export S3CMD_CONFIG="${WORKSPACE}/s3cfg"

    # Create the credential file to access the object storage with s3cmd
    echo "# Setup endpoint
host_base = $S3_HOST
host_bucket = $S3_HOST
use_https = True

# Setup access keys
access_key = $S3_ACCESS_KEY
secret_key = $S3_SECRET_KEY

# Enable S3 v4 signature APIs
signature_v2 = False" > "$S3CMD_CONFIG"
}
