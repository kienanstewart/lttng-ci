def call() {
  LIBDIR = "lib"
  LIBDIR_ARCH = LIBDIR
  ARCH_64bit = sh(
    script: 'file -L /bin/bash | grep -q "64-bit"',
    returnStatus: true,
  )
  ARCH_64bit = ARCH_64bit == 0
  if (ARCH_64bit && (fileExists('/etc/redhat-release') || fileExists('/etc/products.d/SLES.prod') || fileExists('/etc/yocto-release'))) {
    LIBDIR_ARCH = "${LIBDIR}64"
  }

  return LIBDIR_ARCH
}
