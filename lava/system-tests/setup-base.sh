#!/bin/bash
# SPDX-FileCopyrightText: 2021 Jonathan Rajotte <jonathan.rajotte-julien@efficios.com>
# SPDX-FileCopyrightText: 2025 Michael Jeanson <mjeanson@efficios.com>
# SPDX-License-Identifier: GPL-3.0-or-later

set -exu

chmod 755 /

# Reset and mount the local drive on /scratch
mkfs.ext4 -q -F "$SCRATCH_DEVICE"
mkdir "$SCRATCH_DIR"
mount "$SCRATCH_DEVICE" "$SCRATCH_DIR"

# Get the nameserver address from the in-kernel dhcp client
grep ^nameserver /proc/net/pnp > /etc/resolv.conf
grep ^domain /proc/net/pnp >> /etc/resolv.conf

# Add the tracing group expected by lttng-tools
groupadd tracing

depmod -a

# Setup ssh access
mkdir -p /root/.ssh
chmod 700 /root/.ssh
cp lava/system-tests/authorized_keys /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

if [[ "${CONFIGURE_DAX}" == "True" ]]; then
    findmnt
    fdisk -l /dev/pmem0
    modprobe dax_pmem
    apt-get install -y ndctl
    ndctl list -v
    ndctl create-namespace --mode fsdax --map mem -e namespace0.0 -f
    mkfs.ext4 -b 4096 -E stride=512 -F /dev/pmem0
    umount /dev/shm
    mount -o dax=always /dev/pmem0 /dev/shm
fi
