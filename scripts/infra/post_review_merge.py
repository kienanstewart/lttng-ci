#!/usr/bin/env python3
#
# SPDX-License-Identifier: GPL-2.0-only
# SPDX-FileCopyrightText: 2026 Kienan Stewart <kstewart@efficios.com>
#

import argparse
import base64
import logging
import os
import pathlib
import re
import sys

import redminelib


def reference_redmine_issue(redmine, issue_id, message, **kwargs):
    if "noop" in kwargs and kwargs["noop"]:
        logging.info(
            "Would have referenced issue id={}, message={}".format(issue_id, message)
        )
        return

    redmine.issue.update(issue_id, notes=message)


def resolve_redmine_issue(redmine, issue_id, message, **kwargs):
    resolved_status_id = None
    for status in redmine.issue_status.all():
        if status.name == "Resolved":
            resolved_status_id = status.id

    if resolved_status_id is None:
        raise Exception("Could not find id for status by name '{}'".format("Resolved"))

    if "noop" in kwargs and kwargs["noop"]:
        logging.info("Would have resolved issue id={}".format(issue_id))
        return

    redmine.issue.update(issue_id, notes=message, status_id=resolved_status_id)


def do_redmine_verbs(tracker, **kwargs):
    if "commit_message" not in kwargs:
        raise Exception("No commit message")

    if "event" not in kwargs:
        raise Exception("No event defined")

    api_key = os.getenv(
        "REDMINE_{}_API_KEY".format(tracker["name"]), os.getenv("REDMINE_API_KEY", None)
    )
    if api_key is None:
        raise Exception(
            "No API key found in environment for tracker '{}'".format(tracker["url"])
        )

    pattern = re.compile(tracker["regex"], flags=re.MULTILINE)
    results = pattern.findall(kwargs["commit_message"])
    if not results:
        logging.info(
            "No matches for pattern '{}' in commit message".format(tracker["regex"])
        )
        return

    # Test connection
    redmine = redminelib.Redmine(tracker["url"], key=api_key)
    actions = {
        "References": reference_redmine_issue,
        "Refs": reference_redmine_issue,
        "Resolves": resolve_redmine_issue,
    }

    logging.info("{} matches for pattern '{}'".format(len(results), tracker["regex"]))
    for _match in results:
        verb = _match[tracker["verb"]]
        issue_id = _match[tracker["id"]]
        link = tracker["link"].format(verb=verb, id=issue_id)
        logging.debug("verb={}, id={}, link={}".format(verb, issue_id, link))

        if verb not in actions.keys():
            raise Exception("Unknown verb: '{}'".format(verb))

        message = tracker["messages"][
            "{}:{}".format(
                kwargs["event"], "resolves" if verb == "Resolves" else "references"
            )
        ].format(
            **kwargs
            | {
                "verb": verb,
                "verb_past_tense": "resolved" if verb == "Resolves" else "referenced",
            }
        )
        action_kwargs = kwargs | {
            "issue_link": link,
            "issue_id": issue_id,
            "message": message,
        }
        actions[verb](redmine, **action_kwargs)


MESSAGES = {
    "change-merged:resolves": """
Automatically closing this issue because the following commit is now merged:

* *Commit*: <code>{subject}</code>{commit_part}
* *Gerrit change*: "{number}":{gerrit_url}
* *Branch*: <code>{branch}</code>
""",
    "change-merged:references": """
The following merged commit references this issue:

* *Commit*: <code>{subject}</code>{commit_part}
* *Gerrit change*: "{number}":{gerrit_url}
* *Branch*: <code>{branch}</code>
""",
}

GERRIT_PROJECT_TO_GITHUB = {
    "lttng-tools": "lttng/lttng-tools",
    "lttng-ust": "lttng/lttng-ust",
    "lttng-modules": "lttng/lttng-modules",
    "lttng-docs": "lttng/lttng-docs",
    "lttng-ci": "lttng/lttng-ci",
    "lttng-ivc": "lttng/lttng-ivc",
    "lttng-ust-benchmarks": "lttng/lttng-ust-benchmarks",
    "babeltrace": "efficios/babeltrace",
    "barectf": "efficios/barectf",
    "normand": "efficios/normand",
    "argpar": "efficios/argpar",
    "libside": "efficios/libside",
    "userspace-rcu": "urcu/userspace-rcu",
    "librseq": "compudj/librseq",
}


TRACKERS = {
    "bugs": {
        "name": "bugs",
        "url": "https://bugs.lttng.org",
        "regex": r"^(?P<verb>Resolves|References|Refs):\s+P-(?P<id>\d+)$",
        "verb": 0,
        "id": 1,
        "link": "https://bugs.lttng.org/issues/{id}",
        "messages": MESSAGES,
    },
    "support": {
        "name": "support",
        "url": "https://support.efficios.com",
        "regex": r"^(?P<verb>Resolves|References|Refs):\s+S-(?P<id>\d+)$",
        "verb": 0,
        "id": 1,
        "link": "https://bugs.lttng.org/issues/{id}",
        "messages": MESSAGES,
    },
}

HOOKS = {
    "change-merged": [
        {
            "function": do_redmine_verbs,
            "kwargs": {
                "tracker": TRACKERS["bugs"],
            },
        },
        {
            "function": do_redmine_verbs,
            "kwargs": {
                "tracker": TRACKERS["support"],
            },
        },
    ],
}


def run_hooks(
    hooks,
    project,
    event,
    gerrit_url,
    branch,
    commit_message,
    subject=None,
    number=None,
    commit_id=None,
    noop=False,
):
    logging.debug(
        "{} for project {} on branch {}, url={}".format(
            event, project, branch, gerrit_url
        )
    )
    logging.debug("Message:\n---\n{}---".format(commit_message))
    if event not in hooks.keys() or len(hooks[event]) == 0:
        logging.warning("No hooks defined for event '{}'".format(event))
        return

    if commit_id:
        short_commit_id = commit_id[:8]
        github_repo = GERRIT_PROJECT_TO_GITHUB.get(project)

        if github_repo:
            commit_part = ' ("{}":https://github.com/{}/commit/{})'.format(
                short_commit_id, github_repo, commit_id
            )
        else:
            commit_part = " ({})".format(short_commit_id)
    else:
        commit_part = ""

    errors = False
    for hook in hooks[event]:
        try:
            args = hook.get("args", list())
            kwargs = hook.get("kwargs", dict())
            function = hook["function"]
            kwargs |= {
                "project": project,
                "gerrit_url": gerrit_url,
                "event": event,
                "branch": branch,
                "commit_message": commit_message,
                "subject": subject,
                "number": number,
                "commit_part": commit_part,
                "noop": noop,
            }
            logging.debug(
                "Calling hook '{}', args: {}, kwargs: {}".format(
                    function.__name__, args, kwargs
                )
            )
            function(*args, **kwargs)
        except Exception as e:
            logging.error(
                "Exception while handling hook '{}': {}".format(
                    hook["function"].__name__, str(e)
                )
            )
            errors = True

    return errors


def get_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s",
        "--silent",
        help="Only output errors",
        dest="log_level",
        action="store_const",
        const=logging.WARNING,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Increase verbosity",
        dest="log_level",
        action="store_const",
        const=logging.DEBUG,
    )
    parser.add_argument(
        "-n",
        "--noop",
        help="Don't commit any changes to trackers",
        action="store_true",
    )

    parser.add_argument(
        "-m",
        "--message",
        type=pathlib.Path,
        help="A file containing the commit. Cannot be used with `--base64-message`",
        default=None,
    )
    parser.add_argument(
        "--base64-message",
        type=str,
        help="A base64 encoded commit message. Cannot be used with `-m|--message`",
        default=None,
    )
    parser.add_argument("-b", "--branch", help="The gerrit branch")
    parser.add_argument("-e", "--event", help="The gerrit event type")
    parser.add_argument("-u", "--url", help="Gerrit changeset URL")
    parser.add_argument("-p", "--project", help="Gerrit project")
    parser.add_argument("--subject", help="Change subject")
    parser.add_argument("--number", help="Change number")
    parser.add_argument("--commit-id", help="Merged commit ID (SHA1)")
    return parser


def main(args):
    logging.basicConfig(level=logging.INFO)
    parser = get_parser()
    args = parser.parse_args(args)
    if args.log_level:
        logging.getLogger().setLevel(args.log_level)

    if args.base64_message and args.message:
        raise Exception("Cannot specify for `-m|--message` and `--base64-message`")

    message = ""
    if args.message:
        with open(args.message, "r") as f:
            message = f.read()

    if args.base64_message:
        message = base64.b64decode(args.base64_message, validate=True).decode("utf-8")

    # Undo the `"` → `\"` escaping that the Jenkins Gerrit Trigger plugin
    # applies to `GERRIT_CHANGE_SUBJECT` (and other string parameters).
    subject = args.subject

    if subject is not None:
        subject = subject.replace('\\"', '"')

    return run_hooks(
        HOOKS,
        args.project,
        args.event,
        args.url,
        args.branch,
        message,
        subject=subject,
        number=args.number,
        commit_id=args.commit_id,
        noop=args.noop,
    )


if __name__ == "__main__":
    errors = main(sys.argv[1:])
    sys.exit(1 if errors else 0)
