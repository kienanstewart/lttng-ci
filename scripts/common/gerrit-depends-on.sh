#!/usr/bin/bash
#
# SPDX-FileCopyrightText: Kienan Stewart <kstewart@efficios.com>
# SPDX-LicenseIdentifier: GPL-3.0-or-later
#
# Based on scripts/lttng-tools/gerrit-depends-on.sh
#

set -exu

GERRIT_NAME=${GERRIT_NAME:-}
WORKSPACE=${WORKSPACE:-}
PROJECT_NAME=${PROJECT_NAME:-}

gerrit_url="https://${GERRIT_NAME}"
gerrit_query="&o=CURRENT_REVISION&o=DOWNLOAD_COMMANDS"
gerrit_json_query=".[0].revisions[.[0].current_revision].ref"
gerrit_json_query_status=".[0].status"

re="Depends-on: ([a-z0-9_-]+): ([^'$'\n'']*)"
property_file="${WORKSPACE}/gerrit_custom_dependencies.properties"

# Create the property file even if it ends up being empty
touch "$property_file"

pushd "${WORKSPACE}/src/${PROJECT_NAME}"

git rev-list --format=%B --max-count=1 HEAD | while read -r line; do
    # Deactivate debug mode to prevent the gcc warning publisher from picking up
    # compiler error present in the commit message.
    set +x
    if ! [[ ${line} =~ ${re} ]]; then
        set -x
        continue
    fi
    set -x

    project=${BASH_REMATCH[1]}
    project_sanitize=${BASH_REMATCH[1]//-/_}
    gerrit_id=${BASH_REMATCH[2]}

    # Check to see if the change is merged or not
    # Get the change latest ref
    case $project in
        lttng-*)
            # This is necessary since a cherry pick can have the same change id
            # across branches. Still this is only valid for projects where the
            # branch name fits the same branch name style of the lttng-tools
            # project.
            # We will need to be much more clever if the situation arise where
            # we need to depends-on a cherry picked change id for the
            # userspace-rcu or babeltrace project. Until then let's use this
            # hack. The quick solution to this is to tell the committer to change
            # the change id. We could also be clever and require that the
            # "branch name" be included in the `Depends-on` clause.
            local_query="${gerrit_url}/changes/?q=change:${gerrit_id}+branch:${GERRIT_BRANCH}${gerrit_query}"
            ;;
        *)
            local_query="${gerrit_url}/changes/?q=change:${gerrit_id}${gerrit_query}"
            ;;
    esac

    json_doc=$(curl "$local_query" | tail -n+2)
    count=$(jq -r '. | length' <<< "$json_doc")
    if [ "$count" != "1" ]; then
        echo "Expected an array of size 1 got $count"
        exit 1
    fi

    ref=$(jq -r "$gerrit_json_query" <<< "$json_doc")
    change_status=$(jq -r "$gerrit_json_query_status" <<< "$json_doc")
    if [ "$change_status" == "MERGED" ] || [ "$change_status" == "ABANDONED" ]; then
        # If the change was merged or abandoned, trust that the CI's last artifacts
        # for the project are sufficient as don't record the GERRIT_DEP_ property
        # for this project.
        continue
    fi

    # Export the GERRIT_DEP_... into the property file for further jenkins usage
    # Bash case modification e.g. `${x^^}` was introduced in bash 4. MacOSX provides
    # only bash 3.x, so use 'tr' to upper case
    project_sanitize_upper="$(echo "${project_sanitize}" | tr '[:lower:]' '[:upper:]')"
    echo "GERRIT_DEP_${project_sanitize_upper}=${gerrit_id}" >> "$property_file"
    #  Deactivate tests for the project
    echo "${project_sanitize_upper}_RUN_TESTS=no" >> "$property_file"

    # The build.sh script from userspace-rcu expects the source to be located in
    # `liburcu` instead of userspace-rcu. Accommodate for this here.
    if [ "$project" = "userspace-rcu" ]; then
        clone_directory="liburcu"
    else
        clone_directory="$project"
    fi

    clone_directory="$WORKSPACE/src/$clone_directory"

    git clone "${gerrit_url}/${project}" "$clone_directory"
    pushd "$clone_directory"
    git fetch "${gerrit_url}/${project}" "$ref"
    git checkout FETCH_HEAD
    popd
done

popd
cat "${property_file}"
