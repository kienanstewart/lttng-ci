#!/bin/bash -eux
#
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-LicenseIdentifier: GPL-2.0-only
#

if [[ "${PROJECT_NAME}" == "${GERRIT_PROJECT}" ]] ; then
    (
        cd "src/${PROJECT_NAME}"
        git fetch "https://${GERRIT_HOST}/${GERRIT_PROJECT}" "${GERRIT_REFSPEC}"
        git checkout FETCH_HEAD
    )
fi
