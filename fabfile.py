import base64
import json

import requests
import os
from fabric import Connection, Config, task
from pathlib import PosixPath


def _get_latest_github_release(org, repo):
    """Return the latest release tag from GitHub"""
    r = requests.get(f"https://api.github.com/repos/{org}/{repo}/releases/latest")
    r.raise_for_status()
    return r.json()["tag_name"]


UTILITIES_BRANCH = "main"
EMIT_LOG_MESSAGES = os.environ.get("EMIT_LOG_MESSAGES", "true") == "true"
TARGET_RELEASE = os.environ.get("TARGET_RELEASE")
TARGET_USER = "cluebotng"
TOOL_DIR = PosixPath("/data/project") / TARGET_USER

c = Connection(
    "login.toolforge.org",
    config=Config(
        overrides={
            "sudo": {
                "user": f'tools.{TARGET_USER}',
                "prefix": "/usr/bin/sudo -ni",
            }
        }
    ),
)


def __get_file_contents(path: str, parent: str = "static") -> str:
    with (PosixPath(__file__).parent / parent / path).open("r") as fh:
        return fh.read()


def __write_remote_file_contents(
    path: str, contents: str, overwrite: bool = True, replace_vars=None
):
    replace_vars = {} if replace_vars is None else replace_vars
    for key, value in replace_vars.items():
        contents = contents.replace(f'{"{{"} {key} {"}}"}', value)
    encoded_contents = base64.b64encode(contents.encode("utf-8")).decode("utf-8")
    overwrite_check = f"test -f '{path}' || " if not overwrite else ""
    c.sudo(
        f"bash -c \"umask 026 && ({overwrite_check}base64 -d > '{path}' <<< '{encoded_contents}')\""
    )


def _setup():
    """Setup the core directory structure"""
    c.sudo(f'mkdir -p {TOOL_DIR / "apps"}')
    c.sudo(f'mkdir -p {TOOL_DIR / "apps" / "core"}')
    c.sudo(f'mkdir -p {TOOL_DIR / "apps" / "core" / "releases"}')
    c.sudo(
        f'bash -c \'test -d {TOOL_DIR / "apps" / "utilities"} || '
        f'git clone https://github.com/cluebotng/utilities.git {TOOL_DIR / "apps" / "utilities"}\''
    )


def _restart_jobs(targets=None):
    if targets is None:
        targets = ["bot", "core", "webservice", "grafana-alloy"]

    for target in targets:
        print(f"Restarting {target}")
        if target == "webservice":
            c.sudo(
                f"XDG_CONFIG_HOME={TOOL_DIR} toolforge webservice buildservice restart"
            )
        else:
            c.sudo(f"XDG_CONFIG_HOME={TOOL_DIR} toolforge jobs restart {target}")


def _update_utilities():
    """Update the utilities release."""
    print(f"Updating utilities")
    release_dir = TOOL_DIR / "apps" / "utilities"

    c.sudo(f"git -C {release_dir} reset --hard")
    c.sudo(f"git -C {release_dir} clean -fd")
    c.sudo(f"git -C {release_dir} fetch -a")
    c.sudo(f"git -C {release_dir} checkout {UTILITIES_BRANCH}")
    c.sudo(f"git -C {release_dir} pull origin {UTILITIES_BRANCH}")

    print("Updating lighttpd configuration")
    c.sudo(f'cp -fv {release_dir / "lighttpd.conf"} {TOOL_DIR}/.lighttpd.conf')


def _update_jobs():
    """Update the job config."""
    if not (PosixPath(__file__).parent / "jobs" / f"{TARGET_USER}.yaml").exists():
        # Migrated to components
        return

    print(f"Updating jobs")
    database_user = (
        c.sudo(
            f"awk -F= '{'{'}if($1 == \"user\") print $2{'}'}' {TOOL_DIR / 'replica.my.cnf'}",
            hide="stdout",
        )
        .stdout.strip()
        .strip("'")
        .strip('"')
    )

    __write_remote_file_contents(
        (TOOL_DIR / "jobs.yaml").as_posix(),
        __get_file_contents(f"{TARGET_USER}.yaml", parent="jobs"),
        replace_vars={
            "tool_dir": TOOL_DIR.as_posix(),
            "database_user": database_user,
        },
    )

    c.sudo(f'XDG_CONFIG_HOME={TOOL_DIR} toolforge jobs load {TOOL_DIR / "jobs.yaml"}')


def _update_bot():
    """Update the bot release."""
    target_release = TARGET_RELEASE or _get_latest_github_release("cluebotng", "bot")
    print(f"Moving bot to {target_release}")

    # Update the latest image to our target release
    c.sudo(
        f"XDG_CONFIG_HOME={TOOL_DIR} toolforge "
        "build start -L "
        f"--ref {target_release} "
        "-i bot "
        "https://github.com/cluebotng/bot.git"
    )

    return target_release


def _update_report():
    """Update the report release."""
    target_release = TARGET_RELEASE or _get_latest_github_release("cluebotng", "report")
    print(f"Moving report to {target_release}")

    # Update the latest image to our target release
    c.sudo(
        f"XDG_CONFIG_HOME={TOOL_DIR} toolforge "
        "build start -L "
        f"--ref {target_release} "
        "-i report-interface "
        "https://github.com/cluebotng/report.git"
    )

    # Ensure the service template exists
    __write_remote_file_contents(
        TOOL_DIR / "service.template", __get_file_contents("report/service.template")
    )

    return target_release


def _update_irc_relay():
    """Update the IRC relay release."""
    target_release = _get_latest_github_release("cluebotng", "irc_relay")
    print(f"Moving irc-relay to {target_release}")

    # Update the latest image to our target release
    c.sudo(
        f"XDG_CONFIG_HOME={TOOL_DIR} toolforge "
        "build start -L "
        f"--ref {target_release} "
        "-i irc-relay "
        "https://github.com/cluebotng/irc_relay.git"
    )

    return target_release


def _hack_kubernetes_objects():
    """Deal with direct kubernetes objects [T400940]."""
    network_policies = []
    network_policies.append(__get_file_contents("core.yaml", parent="static/kubernetes/network-policy"))
    network_policies.append(__get_file_contents("irc-relay.yaml", parent="static/kubernetes/network-policy"))
    for network_policy in network_policies:
        encoded_contents = base64.b64encode(network_policy.encode("utf-8")).decode("utf-8")
        c.sudo(f'bash -c "base64 -d <<<{encoded_contents} | kubectl apply -f-"')


def _update_core():
    """Update the (image) core release."""
    target_release = TARGET_RELEASE or _get_latest_github_release("cluebotng", "external-core")
    print(f"Moving core to {target_release}")

    # Update the latest image to our target release
    c.sudo(
        f"XDG_CONFIG_HOME={TOOL_DIR} toolforge "
        "build start -L "
        f"--ref {target_release} "
        "-i core "
        "https://github.com/cluebotng/external-core.git"
    )
    return target_release


def _update_metrics_relay():
    """Update the grafana allow release."""
    target_release = _get_latest_github_release("cluebotng", "external-grafana-alloy")
    print(f"Moving grafana-alloy to {target_release}")

    # Update the latest image to our target release
    c.sudo(
        f"XDG_CONFIG_HOME={TOOL_DIR} toolforge "
        "build start -L "
        f"--ref {target_release} "
        "-i grafana-alloy "
        "https://github.com/cluebotng/external-grafana-alloy.git"
    )


def _do_log_message(message: str):
    """Emit a log message (from the tool account)."""
    c.sudo(f"{'' if EMIT_LOG_MESSAGES else 'echo '}dologmsg '{message}'")


@task()
def deploy_utilities(c):
    """Deploy the utilities to the current release."""
    _setup()
    _update_utilities()


@task()
def deploy_report(c):
    """Deploy the report interface to the current release."""
    target_release = _update_report()
    _restart_jobs(["webservice"])
    _do_log_message(f"report deployed @ {target_release}")


@task()
def deploy_bot(c):
    """Deploy bot to the current release."""
    target_release = _update_bot()
    _restart_jobs(["bot"])
    _do_log_message(f"bot deployed @ {target_release}")


@task()
def deploy_core(c):
    """Deploy the core to the current release."""
    _setup()
    target_release = _update_core()
    _restart_jobs(["core"])
    _do_log_message(f"core deployed @ {target_release}")


@task()
def deploy_metrics_relay(c):
    """Deploy the metrics relay to the current release."""
    _update_metrics_relay()
    _restart_jobs(["grafana-alloy"])


@task()
def deploy_irc_relay(c):
    """Deploy the irc relay to the current release."""
    target_release = _update_irc_relay()
    _restart_jobs(["irc-relay"])
    _do_log_message(f"irc-relay deployed @ {target_release}")


@task()
def deploy_jobs(c):
    """Deploy the jobs config."""
    _update_jobs()
    _hack_kubernetes_objects()


@task()
def deploy(c):
    """Deploy all apps to the current release."""
    _setup()
    _update_utilities()
    _update_report()
    _update_core()
    _update_bot()
    _update_irc_relay()
    _update_metrics_relay()
    _update_jobs()
    _restart_jobs()
