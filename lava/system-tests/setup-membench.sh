#!/usr/bin/bash
#
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
# SPDX-License-Identifier: GPL-2.0-only
#

set -exu

# Install dependencies
apt-get update -y

if $(which membench) ; then
    exit 0
fi

if apt-get install -y sc-membench ; then
    exit 0
fi

echo "Installing build deps" >&2
apt-get install -f libhugetlbfs-dev libhwloc-dev libnuma-dev

echo "Building from source" >&2
SRC_DIR=$(mktemp -d)
git clone https://github.com/SpareCores/sc-membench "${SRC_DIR}"
cd "${SRC_DIR}"

prefix=/usr make all -j $(nproc)
prefix=/usr make install
