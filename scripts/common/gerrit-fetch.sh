#!/bin/bash -eux
#
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-LicenseIdentifier: GPL-2.0-only
#

SRC_DIR="src/${PROJECT_NAME}"
if [[ "${PROJECT_NAME}" == "userspace-rcu" ]]; then
    SRC_DIR="src/liburcu"
fi

if [[ "${PROJECT_NAME}" == "${GERRIT_PROJECT}" ]] ; then
    (
        cd "${SRC_DIR}"
        git fetch "https://${GERRIT_HOST}/${GERRIT_PROJECT}" "${GERRIT_REFSPEC}"
        git checkout FETCH_HEAD
    )
fi
