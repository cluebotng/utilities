#!/usr/bin/env python3
"""
Helper script to deal with the terrible configs k8s requires.
"""
import argparse
import json
import subprocess
import sys
from typing import List, Tuple

SUPPORTED_APPS = {
    "core": {
        "image": "docker-registry.tools.wmflabs.org/toolforge-bullseye-standalone:latest",
        "cwd": "/data/project/cluebotng/apps/core/current",
        "command": ["./cluebotng", "-l", "-m", "live_run"],
        "ports": [(3565, "TCP")],
        "limits": {"cpu": "0.1", "memory": "512Mi"},
    },
    "bot": {
        "image": "docker-registry.tools.wmflabs.org/toolforge-php74-sssd-base:latest",
        "cwd": "/data/project/cluebotng/apps/bot",
        "command": ["php", "-f", "cluebot-ng.php"],
        "limits": {"cpu": "0.5", "memory": "2048Mi"},
        "livenessCommand": ["php", "-f", "/data/project/cluebotng/apps/bot/health_check.php"],
    },
    "irc-relay": {
        "image": "docker-registry.tools.wmflabs.org/toolforge-python39-sssd-base:latest",
        "cwd": "/data/project/cluebotng/apps/irc_relay",
        "command": ["./relay.py"],
        "ports": [(3334, "UDP")],
        "limits": {"cpu": "0.1", "memory": "100Mi"},
    },
}


def build_deployment():
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "cbng",
            "namespace": "tool-cluebotng",
        },
        "spec": {
            "selector": {"matchLabels": {"cluebot.toolsforge.org/role": "cbng"}},
            "template": {
                "metadata": {"labels": {"cluebot.toolsforge.org/role": "cbng"}},
                "spec": {
                    "containers": [
                        {**{
                            "name": task_name,
                            "command": [*task["command"]],
                            "env": [
                                {"name": "HOME", "value": "/data/project/cluebotng"}
                            ],
                            "image": task["image"],
                            "imagePullPolicy": "Always",
                            # Note: If we're in the same pod, this is not required
                            # "ports": [
                            #     {"containerPort": port, "protocol": proto}
                            #     for port, proto in task["ports"]
                            # ],
                            "resources": {"limits": task["limits"], "requests": task["limits"]},
                            "volumeMounts": [
                                {"mountPath": "/data/project", "name": "home"}
                            ],
                            "workingDir": task["cwd"],
                        }, **({
                            "livenessProbe": {
                                "exec": {
                                    "command": task["livenessCommand"]
                                }
                            }
                        } if "livenessCommand" in task else {})}
                        for task_name, task in SUPPORTED_APPS.items()
                    ] + [
                        # This is an awful hack to deal with the lack of services
                        # We can likely just hard code this if we stick with this
                        # 'everything in one pod' model, which is also a hack
                        {
                            "name": "discovery",
                            "command": [
                                "/bin/sh",
                                "-c",
                                "--",
                                (
                                    "python3 -m pip install --upgrade pymysql &&"
                                    " /data/project/cluebotng/apps/utilities/update_node.py"
                                ) + "".join([
                                    " --task-name {}".format(task_name)
                                    for task_name in SUPPORTED_APPS.keys()
                                ]),
                            ],
                            "env": [
                                {"name": "HOME", "value": "/data/project/cluebotng"}
                            ],
                            "image": "docker-registry.tools.wmflabs.org/toolforge-python39-sssd-base:latest",
                            "imagePullPolicy": "Always",
                            "volumeMounts": [
                                {"mountPath": "/data/project", "name": "home"}
                            ],
                        },
                    ],
                    "dnsPolicy": "ClusterFirst",
                    "restartPolicy": "Always",
                    "volumes": [
                        {
                            "hostPath": {"path": "/data/project", "type": "Directory"},
                            "name": "home",
                        }
                    ],
                },
            },
        },
    }
    return deployment


def build_and_apply():
    deployable = json.dumps(build_deployment(), indent=4)
    apply_deployable(deployable)


def apply_deployable(deployment):
    p = subprocess.run(
        ["kubectl", "apply", "--validate=true", "-f", "-"],
        input=deployment.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if p.returncode != 0:
        print("Error deploying:")
        print(p.stderr.decode("utf-8"))
        sys.exit(p.returncode)

    print("Successfully deployed:")
    print(p.stdout.decode("utf-8"))


def delete(soft_fail=False):
    p = subprocess.run(
        ["kubectl", "delete", "deployment", "cbng"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if p.returncode != 0:
        print("Error deleting:")
        print(p.stderr.decode("utf-8"))
        if not soft_fail:
            sys.exit(p.returncode)
    else:
        print("Successfully deleted:")
        print(p.stdout.decode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()

    if args.delete:
        delete(args.deploy)

    if args.deploy:
        build_and_apply()


if __name__ == "__main__":
    main()
