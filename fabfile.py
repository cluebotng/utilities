import requests
import time
from fabric import Connection, Config, task
from pathlib import PosixPath


def _get_latest_github_release(org, repo):
    """Return the latest release tag from GitHub"""
    r = requests.get(f"https://api.github.com/repos/{org}/{repo}/releases/latest")
    r.raise_for_status()
    return r.json()["tag_name"]


BOT_RELEASE = _get_latest_github_release('cluebotng', 'bot')
CORE_RELEASE = _get_latest_github_release('cluebotng', 'core')
REPORT_RELEASE = _get_latest_github_release('cluebotng', 'report')
IRC_RELAY_RELEASE = _get_latest_github_release('cluebotng', 'irc_relay')
UTILITIES_BRANCH = 'main'
TOOL_DIR = PosixPath('/data/project/cluebotng')

c = Connection(
    'login.toolforge.org',
    config=Config(
        overrides={'sudo': {'user': 'tools.cluebotng', 'prefix': '/usr/bin/sudo -ni'}}
    ),
)


def _setup():
    """Setup the core directory structure"""
    c.sudo(f'mkdir -p {TOOL_DIR / "apps"}')
    c.sudo(f'mkdir -p {TOOL_DIR / "apps" / "core"}')
    c.sudo(f'mkdir -p {TOOL_DIR / "apps" / "core" / "releases"}')
    c.sudo(f'test -d {TOOL_DIR / "apps" / "bot"} || '
           f'git clone https://github.com/cluebotng/bot.git {TOOL_DIR / "apps" / "bot"}')
    c.sudo(f'test -d {TOOL_DIR / "apps" / "utilities"} || '
           f'git clone https://github.com/cluebotng/utilities.git {TOOL_DIR / "apps" / "utilities"}')
    c.sudo(f'test -d {TOOL_DIR / "apps" / "report"} || '
           f'git clone https://github.com/cluebotng/report.git {TOOL_DIR / "apps" / "report"}')
    c.sudo(f'ln -sf {TOOL_DIR / "apps" / "report"} {TOOL_DIR / "public_html"}')
    c.sudo(f'test -d {TOOL_DIR / "apps" / "irc_relay"} || '
           f'git clone https://github.com/cluebotng/irc_relay.git {TOOL_DIR / "apps" / "irc_relay"}')


def _stop():
    """Stop all k8s jobs."""
    print('Stopping k8s jobs')
    c.sudo(f"{TOOL_DIR / 'apps' / 'utilities' / 'k8s.py'} --delete")
    c.sudo('webservice stop | true')


def _start():
    """Start all k8s jobs."""
    print('Starting k8s jobs')
    c.sudo(f"{TOOL_DIR / 'apps' / 'utilities' / 'k8s.py'} --deploy")
    c.sudo('webservice start --backend kubernetes')


def _update_utilities():
    """Update the utilities release."""
    print(f'Updating utilities')
    release_dir = TOOL_DIR / 'apps' / 'utilities'

    c.sudo(f'git -C {release_dir} reset --hard')
    c.sudo(f'git -C {release_dir} clean -fd')
    c.sudo(f'git -C {release_dir} fetch -a')
    c.sudo(f'git -C {release_dir} checkout {UTILITIES_BRANCH}')
    c.sudo(f'git -C {release_dir} pull origin {UTILITIES_BRANCH}')

    print('Update job entries')
    c.sudo(f'XDG_CONFIG_HOME={TOOL_DIR} toolforge jobs load {release_dir / "jobs.yaml"}')

    print('Updating lighttpd configuration')
    c.sudo(f'cp -fv {release_dir / "lighttpd.conf"} {TOOL_DIR}/.lighttpd.conf')


def _update_bot():
    """Update the bot release."""
    print(f'Moving bot to {BOT_RELEASE}')
    release_dir = TOOL_DIR / "apps" / 'bot'

    c.sudo(f'git -C {release_dir} reset --hard')
    c.sudo(f'git -C {release_dir} clean -fd')
    c.sudo(f'git -C {release_dir} fetch -a')
    c.sudo(f'git -C {release_dir} checkout {BOT_RELEASE}')

    c.sudo(f'{release_dir / "composer.phar"} self-update')
    c.sudo(f'{release_dir / "composer.phar"} install -d {release_dir}')


def _update_report():
    """Update the report release."""
    print(f'Moving report to {REPORT_RELEASE}')
    release_dir = TOOL_DIR / "apps" / 'report'

    c.sudo(f'git -C {release_dir} reset --hard')
    c.sudo(f'git -C {release_dir} clean -fd')
    c.sudo(f'git -C {release_dir} fetch -a')
    c.sudo(f'git -C {release_dir} checkout {REPORT_RELEASE}')

    c.sudo(f'{release_dir / "composer.phar"} self-update')
    c.sudo(f'{release_dir / "composer.phar"} install -d {release_dir}')


def _update_irc_relay():
    """Update the IRC relay release."""
    print(f'Moving irc_relay to {IRC_RELAY_RELEASE}')
    release_dir = TOOL_DIR / "apps" / 'irc_relay'

    c.sudo(f'git -C {release_dir} reset --hard')
    c.sudo(f'git -C {release_dir} clean -fd')
    c.sudo(f'git -C {release_dir} fetch -a')
    c.sudo(f'git -C {release_dir} checkout {IRC_RELAY_RELEASE}')


def _update_core():
    """Update the core release."""
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


@task()
def restart(c):
    """Restart the k8s jobs, without changing releases."""
    try:
        _stop()
    except:
        pass
    _start()


@task()
def deploy_utilities(c):
    """Deploy the utilities to the current release."""
    _setup()
    _update_utilities()


@task()
def deploy_report(c):
    """Deploy the report interface to the current release."""
    _setup()
    _update_report()


@task()
def deploy_bot(c):
    """Deploy the bot to the current release."""
    _setup()
    _update_bot()
    restart(c)


@task()
def deploy_core(c):
    """Deploy the core to the current release."""
    _setup()
    _update_core()
    restart(c)


@task()
def deploy(c):
    """Deploy all apps to the current release."""
    _setup()
    _update_utilities()
    _update_report()
    _update_core()
    _update_bot()
    _update_irc_relay()
    restart(c)
