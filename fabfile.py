import base64

import requests
import os
import json
import uuid
from fabric import Connection, Config, task
from pathlib import PosixPath


def _get_latest_github_release(org, repo):
    """Return the latest release tag from GitHub"""
    r = requests.get(f"https://api.github.com/repos/{org}/{repo}/releases/latest")
    r.raise_for_status()
    return r.json()["tag_name"]


def _build_composer_command(home_dir, working_dir, command):
    # No php on the host anymore, so execute in a temp container....
    name = f"composer-{uuid.uuid4()}"
    spec = {
        "apiVersion": "v1",
        "spec": {
            "containers": [
                {
                    "name": name,
                    "metadata": {
                        "labels": {
                            "toolforge": "tool",
                            "toolforge.org/mount-storage": "all"
                        }
                    },
                    "stdin": True,
                    "tty": True,
                    "image": "docker-registry.tools.wmflabs.org/toolforge-php82-sssd-base",
                    "command": command,
                    "env": [{"name": "HOME", "value": home_dir.as_posix()}],
                    "volumeMounts": [
                        {
                            "mountPath": "/data/project",
                            "name": "home"
                        },
                    ],
                    "workingDir": working_dir.as_posix()
                }
            ],
            "volumes": [
                {
                    "hostPath": {
                        "path": "/data/project",
                        "type": "Directory"
                    },
                    "name": "home"
                },
            ]
        }
    }

    return (
        "kubectl"
        " run"
        " --image docker-registry.tools.wmflabs.org/toolforge-php82-sssd-base"
        f" {name}"
        " -i"
        " --rm"
        f" --overrides='{json.dumps(spec)}'"
    )


UTILITIES_BRANCH = 'main'
EXTERNAL_ALLOY_RELEASE = '1.10.0'
EXTERNAL_PUSH_GW_RELEASE = '1.11.1'
EXTERNAL_PROMETHEUS_RELEASE = '3.5.0'

TARGET_USER = os.environ.get("TARGET_USER", "cluebotng")
PRODUCTION_USER = "cluebotng"
TOOL_DIR = PosixPath('/data/project') / TARGET_USER

c = Connection(
    'login.toolforge.org',
    config=Config(
        overrides={
            'sudo': {
                'user': f'tools.{os.environ.get("TARGET_USER", TARGET_USER)}',
                'prefix': '/usr/bin/sudo -ni'
            }
        }
    ),
)


def __get_file_contents(path: str, parent: str = 'static') -> str:
    with (PosixPath(__file__).parent / parent / path).open('r') as fh:
        return fh.read()


def __write_remote_file_contents(path: str, contents: str, overwrite: bool = True, replace_vars = None):
    replace_vars = {} if replace_vars is None else replace_vars
    for key, value in replace_vars.items():
        contents = contents.replace(f'{"{{"} {key} {"}}"}', value)
    encoded_contents = base64.b64encode(contents.encode('utf-8')).decode('utf-8')
    overwrite_check = f'test -f \'{path}\' || ' if not overwrite else ""
    c.sudo(f'bash -c "umask 026 && ({overwrite_check}base64 -d > \'{path}\' <<< \'{encoded_contents}\')"')


def _setup():
    """Setup the core directory structure"""
    c.sudo(f'mkdir -p {TOOL_DIR / "apps"}')
    c.sudo(f'mkdir -p {TOOL_DIR / "apps" / "core"}')
    c.sudo(f'mkdir -p {TOOL_DIR / "apps" / "core" / "releases"}')
    c.sudo(f'bash -c \'test -d {TOOL_DIR / "apps" / "bot"} || '
           f'git clone https://github.com/cluebotng/bot.git {TOOL_DIR / "apps" / "bot"}\'')
    c.sudo(f'bash -c \'test -d {TOOL_DIR / "apps" / "utilities"} || '
           f'git clone https://github.com/cluebotng/utilities.git {TOOL_DIR / "apps" / "utilities"}\'')
    c.sudo(f'bash -c \'test -d {TOOL_DIR / "apps" / "report"} || '
           f'git clone https://github.com/cluebotng/report.git {TOOL_DIR / "apps" / "report"}\'')
    c.sudo(f'ln -sf {TOOL_DIR / "apps" / "report"} {TOOL_DIR / "public_html"}')
    c.sudo(f'bash -c \'test -d {TOOL_DIR / "apps" / "irc_relay"} || '
           f'git clone https://github.com/cluebotng/irc_relay.git {TOOL_DIR / "apps" / "irc_relay"}\'')


def _restart_jobs(targets=None):
    if targets is None:
        targets = []
        if TARGET_USER == 'cluebotng-staging':
            targets.extend(["botng", "core", "grafana-alloy"])
        if TARGET_USER == 'cluebotng':
            targets.extend(["bot", "core", "prometheus", "prometheus-pushgateway", "webservice"])

    for target in targets:
        print(f'Restarting {target}')
        if target == 'webservice':
            c.sudo(f"XDG_CONFIG_HOME={TOOL_DIR} toolforge webservice buildservice restart")
        else:
            c.sudo(f'XDG_CONFIG_HOME={TOOL_DIR} toolforge jobs restart {target}')


def _update_utilities():
    """Update the utilities release."""
    print(f'Updating utilities')
    release_dir = TOOL_DIR / 'apps' / 'utilities'

    c.sudo(f'git -C {release_dir} reset --hard')
    c.sudo(f'git -C {release_dir} clean -fd')
    c.sudo(f'git -C {release_dir} fetch -a')
    c.sudo(f'git -C {release_dir} checkout {UTILITIES_BRANCH}')
    c.sudo(f'git -C {release_dir} pull origin {UTILITIES_BRANCH}')

    print('Updating lighttpd configuration')
    c.sudo(f'cp -fv {release_dir / "lighttpd.conf"} {TOOL_DIR}/.lighttpd.conf')


def _update_jobs():
    """Update the job config."""
    print(f'Updating jobs')
    database_user = c.sudo(
        f"awk '{'{'}if($1 == \"user\") print $3{'}'}' {TOOL_DIR / 'replica.my.cnf'}", hide="stdout"
    ).stdout.strip()

    __write_remote_file_contents(TOOL_DIR / "jobs.yaml",
                                 __get_file_contents(f'{TARGET_USER}.yaml', parent='jobs'),
                                 replace_vars={
                                     'tool_dir': TOOL_DIR.as_posix(),
                                     'database_user': database_user,
                                 })

    c.sudo(f'XDG_CONFIG_HOME={TOOL_DIR} toolforge jobs load {TOOL_DIR / "jobs.yaml"}')


def _update_bot():
    """Update the bot release."""
    BOT_RELEASE = _get_latest_github_release('cluebotng', 'bot')
    print(f'Moving bot to {BOT_RELEASE}')
    release_dir = TOOL_DIR / "apps" / 'bot'

    c.sudo(f'git -C {release_dir} reset --hard')
    c.sudo(f'git -C {release_dir} clean -fd')
    c.sudo(f'git -C {release_dir} fetch -a')
    c.sudo(f'git -C {release_dir} checkout {BOT_RELEASE}')

    c.sudo(_build_composer_command(TOOL_DIR, release_dir, ['./composer.phar', 'self-update']))
    c.sudo(_build_composer_command(TOOL_DIR, release_dir, ['./composer.phar', 'install']))

def _update_report():
    """Update the report release."""
    target_release = _get_latest_github_release('cluebotng', 'report')
    print(f'Moving report to {target_release}')

    # Update the latest image to our target release
    c.sudo(
        f"XDG_CONFIG_HOME={TOOL_DIR} toolforge "
        "build start -L "
        f"--ref {target_release} "
        "-i report-interface "
        "https://github.com/cluebotng/report.git"
    )

    # Ensure the service template exists
    __write_remote_file_contents(TOOL_DIR / "service.template",
                                 __get_file_contents('report/service.template'))


def _update_irc_relay():
    """Update the IRC relay release."""
    target_release = _get_latest_github_release('cluebotng', 'irc_relay')
    print(f'Moving irc-relay to {target_release}')

    # Update the latest image to our target release
    c.sudo(
        f"XDG_CONFIG_HOME={TOOL_DIR} toolforge "
        "build start -L "
        f"--ref {target_release} "
        "-i irc-relay "
        "https://github.com/cluebotng/irc_relay.git"
    )


def _update_core():
    """Update the core release."""
    CORE_RELEASE = _get_latest_github_release('cluebotng', 'core')
    print(f'Moving core to {CORE_RELEASE}')
    release_dir = TOOL_DIR / "apps" / "core" / "releases" / CORE_RELEASE

    # Bins
    c.sudo(f'mkdir -p {release_dir}')
    c.sudo(f'bash -c \'test -f {release_dir / "cluebotng"} || wget -nv -O {release_dir / "cluebotng"}'
           f' https://github.com/cluebotng/core/releases/download/{CORE_RELEASE}/cluebotng\'')
    c.sudo(f'chmod 755 {release_dir / "cluebotng"}')

    c.sudo(f'mkdir -p {release_dir / "data"}')
    for obj in {'main_ann.fann', 'bayes.db', 'two_bayes.db'}:
        c.sudo(f'bash -c \'test -f {release_dir / "data" / obj} || wget -nv -O {release_dir / "data" / obj}'
               f' https://github.com/cluebotng/core/releases/download/{CORE_RELEASE}/{obj}\'')
        c.sudo(f'chmod 640 {release_dir / "data" / obj}')

    c.sudo(f'bash -c \'test -f {release_dir}/conf.tar.gz || wget -nv -O {release_dir}/conf.tar.gz'
           f' https://github.com/cluebotng/core/releases/download/{CORE_RELEASE}/conf.tar.gz\'')
    c.sudo(f'tar -C {release_dir} -xvf {release_dir}/conf.tar.gz')
    c.sudo(f'rm -f {release_dir}/conf.tar.gz')

    c.sudo(f'ln -snf {release_dir} {TOOL_DIR / "apps" / "core" / "current"}')


def _update_bot_ng():
    """Update the bot-ng release."""
    BOT_NG_RELEASE = _get_latest_github_release('cluebotng', 'botng')
    print(f'Moving botng to {BOT_NG_RELEASE}')
    release_dir = TOOL_DIR / "apps" / "botng" / "releases" / BOT_NG_RELEASE

    # Bins
    c.sudo(f'mkdir -p {release_dir}')
    c.sudo(f'bash -c \'test -f {release_dir / "botng"} || wget -nv -O {release_dir / "botng"}'
           f' https://github.com/cluebotng/botng/releases/download/{BOT_NG_RELEASE}/botng\'')
    c.sudo(f'chmod 755 {release_dir / "botng"}')

    c.sudo(f'ln -snf {release_dir} {TOOL_DIR / "apps" / "botng" / "current"}')


def _update_grafana_alloy():
    """Update the grafana allow release."""
    print(f'Moving grafana-alloy to {EXTERNAL_ALLOY_RELEASE}')
    release_dir = TOOL_DIR / "apps" / "grafana-alloy" / "releases" / EXTERNAL_ALLOY_RELEASE

    c.sudo(f'mkdir -p {release_dir}')
    c.sudo(f'bash -c \'test -f {release_dir / "alloy"} || (wget -qO {release_dir / "alloy-linux-amd64.zip"}'
           f' https://github.com/grafana/alloy/releases/download/v{EXTERNAL_ALLOY_RELEASE}/alloy-linux-amd64.zip &&'
           f' unzip {release_dir / "alloy-linux-amd64.zip"} alloy-linux-amd64 -d {release_dir} &&'
           f' mv {release_dir / "alloy-linux-amd64"} {release_dir / "alloy"})\'')
    c.sudo(f'chmod 755 {release_dir / "alloy"}')

    c.sudo(f'ln -snf {release_dir} {TOOL_DIR / "apps" / "grafana-alloy" / "current"}')

    __write_remote_file_contents(TOOL_DIR / "apps" / "grafana-alloy" / "config.alloy",
                                 __get_file_contents(f'grafana-alloy/{TARGET_USER}.alloy'))


def _update_prometheus_pushgateway():
    """Update the prometheus push gateway release."""
    print(f'Moving prometheus-pushgateway to {EXTERNAL_PUSH_GW_RELEASE}')
    release_dir = TOOL_DIR / "apps" / "prometheus-pushgateway" / "releases" / EXTERNAL_PUSH_GW_RELEASE

    c.sudo(f'mkdir -p {release_dir}')
    c.sudo(f'bash -c \'test -f {release_dir / "pushgateway"} || (wget -qO-'
           f' https://github.com/prometheus/pushgateway/releases/download/v{EXTERNAL_PUSH_GW_RELEASE}/pushgateway-{EXTERNAL_PUSH_GW_RELEASE}.linux-amd64.tar.gz |'
           f' tar -xzf- -C {release_dir} --strip-components=1 pushgateway-{EXTERNAL_PUSH_GW_RELEASE}.linux-amd64/pushgateway)\'')
    c.sudo(f'chmod 755 {release_dir / "pushgateway"}')

    c.sudo(f'ln -snf {release_dir} {TOOL_DIR / "apps" / "prometheus-pushgateway" / "current"}')


def _update_prometheus():
    """Update the prometheus release."""
    print(f'Moving prometheus to {EXTERNAL_PROMETHEUS_RELEASE}')
    release_dir = TOOL_DIR / "apps" / "prometheus" / "releases" / EXTERNAL_PROMETHEUS_RELEASE

    c.sudo(f'mkdir -p {release_dir}')
    c.sudo(f'bash -c \'test -f {release_dir / "prometheus"} || (wget -qO-'
           f' https://github.com/prometheus/prometheus/releases/download/v{EXTERNAL_PROMETHEUS_RELEASE}/prometheus-{EXTERNAL_PROMETHEUS_RELEASE}.linux-amd64.tar.gz |'
           f' tar -xzf- -C {release_dir} --strip-components=1 prometheus-{EXTERNAL_PROMETHEUS_RELEASE}.linux-amd64/prometheus)\'')
    c.sudo(f'chmod 755 {release_dir / "prometheus"}')

    c.sudo(f'ln -snf {release_dir} {TOOL_DIR / "apps" / "prometheus" / "current"}')

    config_dir = TOOL_DIR / "apps" / "prometheus" / "config"
    c.sudo(f'mkdir -p {config_dir}')
    __write_remote_file_contents(f'{config_dir / "prometheus.yaml"}',
                                 __get_file_contents('prometheus/prometheus.yaml'))
    __write_remote_file_contents(f'{config_dir / "rules.yaml"}',
                                 __get_file_contents('prometheus/rules.yaml'))

    data_dir = TOOL_DIR / "apps" / "prometheus" / "data"
    c.sudo(f'mkdir -p {data_dir}')


def _update_metrics_relay():
    if TARGET_USER == "cluebotng-staging":
        _update_grafana_alloy()

    if TARGET_USER == "cluebotng":
        _update_prometheus()
        _update_prometheus_pushgateway()


@task()
def deploy_utilities(c):
    """Deploy the utilities to the current release."""
    _setup()
    _update_utilities()


@task()
def deploy_report(c):
    """Deploy the report interface to the current release."""
    _update_report()
    _restart_jobs(['webservice'])


@task()
def deploy_bot(c):
    """Deploy bot to the current release."""
    _setup()
    if TARGET_USER == PRODUCTION_USER:
        _update_bot()
        _restart_jobs(['bot'])
    else:
        _update_bot_ng()
        _restart_jobs(['botng'])


@task()
def deploy_core(c):
    """Deploy the core to the current release."""
    _setup()
    _update_core()
    _restart_jobs(['core'])


@task()
def deploy_metrics_relay(c):
    """Deploy the metrics relay to the current release."""
    _setup()
    _update_metrics_relay()
    if TARGET_USER == PRODUCTION_USER:
        _restart_jobs(['prometheus', 'prometheus-pushgateway'])
    else:
        _restart_jobs(['grafana-alloy'])


@task()
def deploy_irc_relay(c):
    """Deploy the irc relay to the current release."""
    if TARGET_USER != PRODUCTION_USER:
        return
    _update_irc_relay()
    _restart_jobs(['irc-relay'])


@task()
def deploy_jobs(c):
    """Deploy the jobs config."""
    _update_jobs()


@task()
def deploy(c):
    """Deploy all apps to the current release."""
    _setup()
    _update_utilities()
    _update_jobs()
    _update_report()
    _update_core()
    _update_bot()
    _update_irc_relay()
    _update_metrics_relay()
    _restart_jobs()
