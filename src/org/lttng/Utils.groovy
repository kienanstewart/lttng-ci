// SPDX-License-Identifier: GPL-2.0-only
// SPDX-FileCopyrightText: 2025 Kienan Stewart <kstewart@efficios.com>

package org.lttng

def uses_arch_libdir() {
  return fileExists('/etc/redhat-release') || fileExists('/etc/products.d/SLES.prod') || fileExists('/etc/yocto-release')
}

def get_lib_arch_directory() {
  LIBDIR = "lib"
  LIBDIR_ARCH = LIBDIR
  ARCH_64bit = sh(
    script: 'file -L /bin/bash | grep -q "64-bit"',
    returnStatus: true,
  )
  ARCH_64bit = ARCH_64bit == 0
  if (ARCH_64bit && uses_arch_libdir()) {
    LIBDIR_ARCH = "${LIBDIR}64"
  }
  return LIBDIR_ARCH
}

def get_axis_path(platform, conf, build, cc) {
  return "platform=${platform}/conf=${conf}/build=${build}/cc=${cc}"
}
