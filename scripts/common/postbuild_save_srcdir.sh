#!/bin/bash -eux

if [[ ! -f "${WORKSPACE}/src.tar.xz" ]]; then
    tar -c -J -f "${WORKSPACE}/src.tar.xz" -C "${WORKSPACE}/src/" "./"
fi
