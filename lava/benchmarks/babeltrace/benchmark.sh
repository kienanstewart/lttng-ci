#!/bin/bash

set -exu
set -o pipefail

# shellcheck source=SCRIPTDIR/../common/utils.sh disable=SC1091
source lava/benchmarks/common/utils.sh

enable_performance_cpu_governor || true
# shellcheck disable=SC2119
enable_coredumps || true

BASE_DIR="$(pwd)"
BT_SRCDIR="$SCRATCH_DIR/babeltrace"
BENCHMARK_DIR="$TMPDIR/ram_disk"
PREFIX="${BENCHMARK_DIR}/opt"
RESULTS_DIR_PREFIX="results/benchmarks/babeltrace"

# Create a 10GB ramdisk for the benchmark
mkdir "$BENCHMARK_DIR"
mount -t tmpfs -o size=10024m none "$BENCHMARK_DIR"

# Checkout the babeltrace git repo
git clone -q "${BT_REPO}" "$BT_SRCDIR"

TRACES=(
    'default'
    'tools_2_10'
    'tools_2_14'
)

TRACE_SINKS=(
    'dummy'
    'text'
)

while read -d ' ' -r commit ; do
    if [ -z "${commit}" ]; then
        echo "Empty commit" >&2
        continue
    fi

    cd "${BT_SRCDIR}"

    # Clean the source dir
    git clean -xdf > /dev/null

    # Checkout the commit to benchmark
    git checkout "${commit}"

    # Build and install babeltrace, a build failure should not abort the whole
    # benchmark run, only skip this commit.
    if ! ./bootstrap > ../bootstrap.log 2>&1 ; then
        # Upload log for analysis
        cat ../bootstrap.log
        echo "[${commit}] bootstrap failed" >&2
        upload_artifact ../bootstrap.log "${RESULTS_DIR_PREFIX}/${commit}/bootstrap.log"
        # A file to signal that there was a failure during the benchmark
        date > ../failed
        upload_artifact ../failed "${RESULTS_DIR_PREFIX}/${commit}/failed"
        continue
    fi

    # `-flto` isn't used since it appears to cause build failures on a number
    # of tags as it is an untested configuration in the CI.
    if ! ./configure \
        CFLAGS='-O3 -g0 -Wno-error' \
        CXXFLAGS='-O3 -g0 -Wno-error' \
        LDFLAGS='' \
        BABELTRACE_DEV_MODE=0 \
        BABELTRACE_DEBUG_MODE=0 \
        BABELTRACE_MINIMAL_LOG_LEVEL=INFO \
        --prefix="$PREFIX" \
        --disable-man-pages \
        --enable-vendor-catch2 \
        --enable-vendor-fmt > ../config.log 2>&1 ; then
        # Upload log
        cat ../config.log
        echo "[${commit}] configure failed" >&2
        upload_artifact ../config.log "${RESULTS_DIR_PREFIX}/${commit}/config.log"
        # A file to signal that there was a failure during the benchmark
        date > ../failed
        upload_artifact ../failed "${RESULTS_DIR_PREFIX}/${commit}/failed"
        continue
    fi

    if ! make -j"$(nproc)" > ../make.log 2>&1 ; then
        # Upload log
        cat ../make.log
        echo "[${commit}] make failed" >&2
        upload_artifact ../make.log "${RESULTS_DIR_PREFIX}/${commit}/make.log"
        # A file to signal that there was a failure during the benchmark
        date > ../failed
        upload_artifact ../failed "${RESULTS_DIR_PREFIX}/${commit}/failed"
        continue
    fi

    if ! make install > ../install.log 2>&1 ; then
        # Upload log
        cat ../install.log
        echo "[${commit}] make install failed" >&2
        upload_artifact ../install.log "${RESULTS_DIR_PREFIX}/${commit}/install.log"
        # A file to signal that there was a failure during the benchmark
        date > ../failed
        upload_artifact ../failed "${RESULTS_DIR_PREFIX}/${commit}/failed"
        continue
    fi

    ldconfig
    BT_BIN=$PREFIX/bin/babeltrace2
    if [ -e "$PREFIX/bin/babeltrace" ] ; then
        echo "Running bt1"
        BT_BIN=$PREFIX/bin/babeltrace
    fi

    cd "$BENCHMARK_DIR"
    for trace in "${TRACES[@]}" ; do
        trace_location_var="TRACE_${trace^^}_LOCATION"
        trace_location="${!trace_location_var}"
        trace_unpack_dir="${BENCHMARK_DIR}/trace_${trace}"

        # Download the test trace once
        if [ ! -d "${trace_unpack_dir}" ] ; then
            mkdir -p "${trace_unpack_dir}"
            curl --silent "${trace_location}" -o - | tar -xzv -C "${trace_unpack_dir}"
        fi

        # Run the benchmark for each sink type
        for sink in "${TRACE_SINKS[@]}" ; do
            # Drop the page cache
            echo 3 | tee /proc/sys/vm/drop_caches

            ARGS=(
                "${trace_unpack_dir}"
            )

            if [[ "${sink}" == "dummy" ]]; then
                ARGS+=("-o" "dummy")
            fi

            python3 "$BASE_DIR/scripts/babeltrace-benchmark/time.py" --output=result --command "$BT_BIN ${ARGS[*]}" --iteration 5 --taskset 0

            upload_artifact result "${RESULTS_DIR_PREFIX}/${commit}/${sink}-${trace}"

            rm -f result
        done
    done

    # Remove the failed file if one exists
    delete_artifact "${RESULTS_DIR_PREFIX}/${commit}/failed" || true
    rm -rf "$PREFIX"

# The trailing space is important for the loop
done <<< "${BT_COMMITS} "
