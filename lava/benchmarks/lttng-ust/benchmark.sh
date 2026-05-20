#!/bin/bash

set -exu
set -o pipefail

# shellcheck source=SCRIPTDIR/../common/utils.sh disable=SC1091
source lava/benchmarks/common/utils.sh

enable_performance_cpu_governor || true
# shellcheck disable=SC2119
enable_coredumps || true

# Setup ram disk
BENCHMARK_DIR="${TMPDIR}/ram_disk"
mkdir "${BENCHMARK_DIR}"
mount -t tmpfs -o size=100024m none "${BENCHMARK_DIR}"

# Clone repos
SRC_DIR="${TMPDIR}/src"
mkdir "${SRC_DIR}"

BABELTRACE_SRC_DIR="${SRC_DIR}/babeltrace"
MODULES_SRC_DIR="${SRC_DIR}/lttng-modules"
TOOLS_SRC_DIR="${SRC_DIR}/lttng-tools"
UST_BENCHMARKS_SRC_DIR="${SRC_DIR}/lttng-ust-benchmarks"
UST_SRC_DIR="${SRC_DIR}/lttng-ust"
URCU_SRC_DIR="${SRC_DIR}/urcu"

git clone --quiet "${BABELTRACE_REPO}" "${BABELTRACE_SRC_DIR}"
git clone --quiet "${LTTNG_MODULES_REPO}" "${MODULES_SRC_DIR}"
git clone --quiet "${LTTNG_TOOLS_REPO}" "${TOOLS_SRC_DIR}"
git clone --quiet "${LTTNG_UST_REPO}" "${UST_SRC_DIR}"
git clone --quiet "${LTTNG_UST_BENCHMARKS_REPO}" "${UST_BENCHMARKS_SRC_DIR}"
if [[ "${LTTNG_UST_BENCHMARKS_BRANCH}" =~ ^refs/ ]]; then
    git -C "${UST_BENCHMARKS_SRC_DIR}" fetch --quiet origin "${LTTNG_UST_BENCHMARKS_BRANCH}"
    git -C "${UST_BENCHMARKS_SRC_DIR}" checkout FETCH_HEAD
else
    git -C "${UST_BENCHMARKS_SRC_DIR}" checkout "${LTTNG_UST_BENCHMARKS_BRANCH}"
fi

git clone --quiet "${URCU_REPO}" "${URCU_SRC_DIR}"

function set_commits_from_ust_commit()
{
    local commit="${1:-${UST_COMMIT}}"

    # The first heuristic is the nearest tag. This is _not_ very good on
    # the master branch, but otherwise it's probably "ok".
    tag="$(git -C "${UST_SRC_DIR}" describe --abbrev=0 "${commit}")"
    vmajor_minor="$(echo "$tag" | cut -d '.' -f 1-2)"

    # Use the .0 release of the major.minor
    tools_commit="${vmajor_minor}.0"
    modules_commit="${vmajor_minor}.0"
    urcu_commit="v0.15.0"
    babeltrace_commit="v2.1.0"
}

function mark_commit_failure()
{
    local msg="${1:-Unknown failure}"
    local file
    file="$(mktemp)"
    echo "[$(date)] ${msg}" > "$file"
    upload_artifact "$file" "$RESULTS_DIR/failed"
    rm -f "$file"
}

function build_urcu()
{
    commit="${1}"
    ret=0
    tag="$(git -C "${URCU_SRC_DIR}" describe)" || true
    if [[ "${commit}" == "$(git -C "${URCU_SRC_DIR}" rev-parse HEAD)" ]] || [[ "${commit}" == "${tag}" ]]; then
        echo "URCU already on commit '${commit}'" >&2
        make -C "${URCU_SRC_DIR}" install
        return $ret
    fi

    LOGS_DIR="$(mktemp -d)"
    if ! (
            set -e
            cd "${URCU_SRC_DIR}"
            git clean -dxf >/dev/null
            git checkout "${commit}"
            ./bootstrap > "${LOGS_DIR}/bootstrap.log" 2>&1
            ./configure \
                CFLAGS="${DEFAULT_CFLAGS}" \
                CPPFLAGS="${DEFAULT_CPPFLAGS}" \
                CXXFLAGS="${DEFAULT_CXXFLAGS}" \
                LDFLAGS="${DEFAULT_LDFLAGS}" \
                --prefix="${PREFIX}" > "${LOGS_DIR}/config.log" 2>&1
            make -j"$(nproc)" > "${LOGS_DIR}/make.log" 2>&1
            make install > "${LOGS_DIR}/install.log" 2>&1
        ); then
        ret=1
        echo "urcu build '${commit}' failed" >&2
        tar -czf logs.tgz -C "${LOG_DIR}/" .
        upload_artifact logs.tgz "${RESULTS_DIR}/logs.tgz"
        rm -f logs.tgz
    fi

    REBUILD_UST=1
    REBUILD_TOOLS=1
    rm -rf "${LOGS_DIR}"
    return $ret
}

function build_babeltrace()
{
    commit="${1}"
    ret=0
    tag="$(git -C "${BABELTRACE_SRC_DIR}" describe)" || true
    if [[ "${commit}" == "$(git -C "${BABELTRACE_SRC_DIR}" rev-parse HEAD)" ]] || [[ "${commit}" == "${tag}" ]]; then
        echo "Babeltrace already on commit '${commit}'" >&2
        make -C "${BABELTRACE_SRC_DIR}" install
        return $ret
    fi

    LOG_DIR="$(mktemp -d)"
    if ! (
            set -e
            cd "${BABELTRACE_SRC_DIR}"
            git clean -dxf >/dev/null
            git checkout "${commit}"
            ./bootstrap > "${LOG_DIR}/bootstrap.log" 2>&1
            ./configure \
                BABELTRACE_DEV_MODE=0 \
                BABELTRACE_DEBUG_MODE=0 \
                BABELTRACE_MINIMAL_LOG_LEVEL=INFO \
                --disable-man-pages \
                CFLAGS="${DEFAULT_CFLAGS}" \
                CPPFLAGS="${DEFAULT_CPPFLAGS}" \
                CXXFLAGS="${DEFAULT_CXXFLAGS}" \
                LDFLAGS="${DEFAULT_LDFLAGS}" \
                --prefix="${PREFIX}" > "${LOG_DIR}/config.log" 2>&1
            make -j"$(nproc)" > "${LOG_DIR}/make.log" 2>&1
            make install > "${LOG_DIR}/install.log" 2>&1
        ); then
        ret=1
        echo "babeltrace build '${commit}' failed" >&2
        tar -czf logs.tgz -C "${LOG_DIR}/" .
        upload_artifact logs.tgz "${RESULTS_DIR}/logs.tgz"
        rm -f logs.tgz
    fi

    rm -rf "${LOG_DIR}"
    return $ret
}

function build_modules()
{
    commit="${1}"
    ret=0
    tag="$(git -C "${MODULES_SRC_DIR}" describe)" || true
    if [[ "${commit}" == "$(git -C "${MODULES_SRC_DIR}" rev-parse HEAD)" ]] || [[ "${commit}" == "${tag}" ]] ; then
        echo "lttng-modules already on commit '${commit}'" >&2
        make -C "${MODULES_SRC_DIR}" modules_install INSTALL_MOD_PATH="$PREFIX/usr" > install.log 2>&1
        depmod --all --basedir="$PREFIX/usr" > depmod.log 2>&1
        return $ret
    fi

    LOG_DIR="$(mktemp -d)"
    if ! (
            set -e
            cd "${MODULES_SRC_DIR}"
            git clean -dxf >/dev/null
            git checkout "${commit}"
            make -j"$(nproc)" > "${LOG_DIR}/make.log" 2>&1
            make modules_install INSTALL_MOD_PATH="$PREFIX/usr" > "${LOG_DIR}/install.log" 2>&1
            depmod --all --basedir="$PREFIX/usr" > "${LOG_DIR}/depmod.log" 2>&1
    ); then
        # It's okay if lttng-modules fails
        ret=0
        echo "lttng-modules build '${commit}' failed" >&2
        tar -czf logs.tgz -C "${LOG_DIR}/" .
        upload_artifact logs.tgz "${RESULTS_DIR}/logs.tgz"
        rm -f logs.tgz
    fi

    rm -rf "${LOG_DIR}"
    return $ret
}

function build_ust()
{
    commit="${1}"
    ret=0
    tag="$(git -C "${UST_SRC_DIR}" describe)" || true
    if [[ "${REBUILD_UST}" == "0" ]]; then
        if [[ "${commit}" == "$(git -C "${UST_SRC_DIR}" rev-parse HEAD)" ]] || [[ "${commit}" == "${tag}" ]]; then
            echo "lttng-ust already on commit '${commit}'" >&2
            make -C "${UST_SRC_DIR}" install
            return $ret
        fi
    fi

    LOG_DIR="$(mktemp -d)"
    if ! (
            set -e
            cd "${UST_SRC_DIR}"
            ./bootstrap > "${LOG_DIR}/bootstrap.log" 2>&1
            ./configure \
                --disable-examples \
                --disable-man-pages \
                CFLAGS="${DEFAULT_CFLAGS}" \
                CPPFLAGS="${DEFAULT_CPPFLAGS}" \
                CXXFLAGS="${DEFAULT_CXXFLAGS}" \
                LDFLAGS="${DEFAULT_LDFLAGS}" \
                --prefix="${PREFIX}" > "${LOG_DIR}/config.log" 2>&1
            make -j"$(nproc)" > "${LOG_DIR}/make.log" 2>&1
            make install > "${LOG_DIR}/install.log" 2>&1
        ); then
        ret=1
        echo "lttng-ust build '${commit}' failed" >&2
        tar -czf logs.tgz -C "${LOG_DIR}/" .
        upload_artifact logs.tgz "${RESULTS_DIR}/logs.tgz"
        rm -f logs.tgz
    fi

    REBUILD_UST=0
    REBUILD_TOOLS=1
    rm -rf "${LOG_DIR}"
    return $ret
}

function build_tools()
{
    commit="${1}"
    ret=0
    tag="$(git -C "${TOOLS_SRC_DIR}" describe)" || true
    if [[ "${REBUILD_TOOLS}" == "0" ]]; then
        if [[ "${commit}" == "$(git -C "${TOOLS_SRC_DIR}" rev-parse HEAD)" ]] || [[ "${commit}" == "${tag}" ]]; then
            echo "lttng-tools already on commit '${commit}'" >&2
            make -C "${TOOLS_SRC_DIR}" install
            return $ret
        fi
    fi

    LOG_DIR="$(mktemp -d)"
    if ! (
            set -e
            cd "${TOOLS_SRC_DIR}"
            ./bootstrap > "${LOG_DIR}/bootstrap.log" 2>&1
            ./configure \
                --disable-doxygen-doc \
                --disable-man-pages \
                --enable-python-bindings \
                CFLAGS="${DEFAULT_CFLAGS}" \
                CPPFLAGS="${DEFAULT_CPPFLAGS}" \
                CXXFLAGS="${DEFAULT_CXXFLAGS}" \
                LDFLAGS="${DEFAULT_LDFLAGS}" \
                --prefix="${PREFIX}" > "${LOG_DIR}/config.log" 2>&1
            make -j"$(nproc)" > "${LOG_DIR}/make.log" 2>&1
            make install > "${LOG_DIR}/install.log" 2>&1
        ); then
        ret=1
        echo "lttng-tools build '${commit}' failed" >&2
        tar -czf logs.tgz -C "${LOG_DIR}/" .
        upload_artifact logs.tgz "${RESULTS_DIR}/logs.tgz"
        rm -f logs.tgz
    fi

    REBUILD_TOOLS=0
    rm -rf "${LOG_DIR}"
    return 0
}

function build_ust_benchmarks()
{
    make -C "${UST_BENCHMARKS_SRC_DIR}" clean \
                EXTRA_CFLAGS="${DEFAULT_CFLAGS}" \
                EXTRA_CPPFLAGS="${DEFAULT_CPPFLAGS}" \
                EXTRA_LDFLAGS="${DEFAULT_LDFLAGS}" \
                LTTNG_MODULES_DIR="${MODULES_SRC_DIR}"
    make -C "${UST_BENCHMARKS_SRC_DIR}" -j"$(nproc)" \
                EXTRA_CFLAGS="${DEFAULT_CFLAGS}" \
                EXTRA_CPPFLAGS="${DEFAULT_CPPFLAGS}" \
                EXTRA_LDFLAGS="${DEFAULT_LDFLAGS}" \
                LTTNG_MODULES_DIR="${MODULES_SRC_DIR}"
}

PREFIX="${BENCHMARK_DIR}/opt"
DEFAULT_CFLAGS='-O3 -g0 -Wno-error'
DEFAULT_CXXFLAGS='-O3 -g0 -Wno-error'
DEFAULT_CPPFLAGS="-I${PREFIX}/include"
DEFAULT_LDFLAGS="-L${PREFIX}/lib"
REBUILD_UST=1
REBUILD_TOOLS=1

python_version="$(python3 --version | cut -d ' ' -f2 | cut -d '.' -f1-2)"
export PYTHONPATH="${PREFIX}/lib/python${python_version}/site-packages"
export PATH="${PREFIX}/bin:${PATH}"
export LD_LIBRARY_PATH="${PREFIX}/lib:"
export PKG_CONFIG_PATH="${PREFIX}/lib/pkgconfig:"

while read -d ' ' -r commit; do
    if [[ -z "${commit}" ]]; then
        echo "Empty commit, skipping" >&2
        continue
    fi

    # Clean-up
    rm -rf "${PREFIX}"
    mkdir "${PREFIX}"

    echo "Commit: '${commit}'" >&2
    UST_COMMIT="${commit}"
    RESULTS_DIR="results/benchmarks/lttng-ust/${UST_COMMIT}"

    # Determine which version of babeltrace, modules, tools, and urcu to use
    # For commits in the master branch of UST it's difficult to pick the correct versions to tools
    set_commits_from_ust_commit "${UST_COMMIT}"

    # Fetch and build urcu
    if ! build_urcu "${urcu_commit}"; then
        mark_commit_failure "urcu build failed"
        continue
    fi

    # Fetch and build babeltrace
    if ! build_babeltrace "${babeltrace_commit}"; then
        mark_commit_failure "babeltrace build failed"
        continue
    fi

    # Fetch and build modules
    if ! build_modules "${modules_commit}"; then
        echo "modules build failed" >&2
        # This is not a hard dependency, we'll simply be missing the kernel benchmark portion
    fi

    # Fetch and build lttng-ust
    if ! build_ust "${UST_COMMIT}"; then
        mark_commit_failure "ust build failed"
        continue
    fi

    # Fetch and build lttng-tools
    if ! build_tools "${tools_commit}"; then
        mark_commit_failure "tools build failed"
        continue
    fi

    # Clean and rebuild lttng-ust-benchmarks
    if ! build_ust_benchmarks; then
        mark_commit_failure "ust benchmarks build failure"
        continue
    fi

    # Run benchmarks
    BENCHMARK_LOG=$(mktemp)
    if ! (
            set -e
            cd "${UST_BENCHMARKS_SRC_DIR}"
            ./benchmarks.py \
                --lttng-modules-commit "${modules_commit}" \
                --lttng-tools-commit "${tools_commit}" \
                --lttng-ust-commit "${UST_COMMIT}" \
                --urcu-commit "${urcu_commit}" > "${BENCHMARK_LOG}" 2>&1
        ) ; then
        mark_commit_failure "benchmarks run failure"
        cat "${BENCHMARK_LOG}"
    else
        # Save results
        upload_artifact "${UST_BENCHMARKS_SRC_DIR}/benchmarks.json" "${RESULTS_DIR}/benchmarks.json"
        delete_artifact "${RESULTS_DIR}/failed" || true
        delete_artifact "${RESULTS_DIR}/logs.tgz" || true
    fi

    rm -f "${BENCHMARK_LOG}"
    # The trailing space is important for the loop
done <<< "${COMMITS} "

umount "${BENCHMARK_DIR}"
