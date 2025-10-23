import configparser
import json
from io import StringIO
from typing import Optional

from fabric import Connection, Config, task
from pathlib import PosixPath


def _get_connection(tool_name: Optional[str] = None) -> Connection:
    return Connection(
        "login.toolforge.org",
        config=(
            Config(
                overrides={
                    "sudo": {
                        "user": f"tools.{tool_name}",
                        "prefix": "/usr/bin/sudo -ni",
                    }
                }
            )
            if tool_name
            else None
        ),
    )


@task()
def update_mysql_credentials(c):
    """Update mysql credentials from workers."""
    user_connection = _get_connection()
    groups = user_connection.run("groups", hide="stdout").stdout.strip().split(" ")

    database_credentials = set()
    for group in groups:
        if group.startswith("tools.cluebotng-worker-"):
            tool_name = group.removeprefix("tools.")
            tool_connection = _get_connection(tool_name)

            config = configparser.ConfigParser()
            config.read_string(
                tool_connection.sudo(
                    f'cat {(PosixPath("/data/project") / tool_name / "replica.my.cnf").as_posix()}',
                    hide="stdout",
                ).stdout
            )
            user = config.get("client", "user")
            password = config.get("client", "password")
            if user and password:
                print(f"Adding credentials from {tool_name}")
                database_credentials.add((user, password))
            else:
                print(f"Failed to find credentials under {tool_name}")

    credentials = json.dumps(
        [
            {"user": username, "pass": password}
            for username, password in database_credentials
        ]
    )

    tool_connection = _get_connection("cluebotng")
    tool_connection.sudo(
        f"XDG_CONFIG_HOME=/data/project/cluebotng toolforge envvars create CBNG_BOT_MYSQL_CREDENTIALS",
        in_stream=StringIO(credentials),
        hide="stdout",
    )
