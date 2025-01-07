def call() {
  commands = [
    "lscpu",
    "free -m",
    "vmstat free",
    "df -H -T",
  ]
  for (command in commands) {
    sh(
      script: command,
      returnStatus: true
    )
  }

    commands = [
    "cat /etc/os-release",
    "cat /etc/release",
    "sw_vers",
    "uname -a"
  ]
  for (command in commands) {
    sh(
      script: command,
      returnStatus: true
    )
  }

  commands = [
    '\$CC --version | head -n1',
    '\$CXX --version | head -n1',
    'gcc --version | head -n1',
    'gcc -dumpmachine',
    'g++ --version | head -n1',
    'g++ -dumpmachine',
    'clang --version',
    'clang++ --version',
    'git --version',
    'bash --version | head -n1',
    '\$MAKE --version | head -n1',
    'cmake --version',
    'automake --version | head -n1',
    'autoconf --version | head -n1',
    'libtool --version | head -n1',
    'libtool -V', // Mac
    '\$BISON --version | head -n1',
    '\$FLEX --version"',
    'swig -version | \$GREP SWIG',
    '\$PYTHON --version',
    '\$PYTHON2 --version',
    '\$PYTHON3 --version',
    'java -version',
    'javac -version',
    'asciidoc --version',
    'xmlto --version',
    'openssl version',
    'pkg-config --version',
  ]
  for (command in commands) {
    sh(
      script: command,
      returnStatus: true
    )
  }
  pkgconfig_mods = [
    'glib-2.0',
    'libdw',
    'libelf',
    'libxml-2.0',
    'msgpack',
    'popt',
    'uuid',
    'zlib',
  ]
  for (pkgconfig_mod in pkgconfig_mods) {
      sh(
      script: "pkg-config --modversion $pkgconfig_mod",
      returnStatus: true
    )
  }
}
