#!/usr/bin/env python3
"""
Helper script to deal with the terrible configs k8s requires.
"""
import argparse
import json
import subprocess
import sys
import os
from typing import List, Tuple

BASE_DIR = os.environ['HOME']
TOOL_NAME = os.environ['USER'].split('tools.')[1]
SUPPORTED_APPS = {
    "core": {
        "image": "docker-registry.tools.wmflabs.org/toolforge-bullseye-standalone:latest",
        "cwd": f"{BASE_DIR}/apps/core/current",
        "command": ["./cluebotng", "-l", "-m", "live_run"],
        "ports": [(3565, "TCP")],
        "limits": {"cpu": "0.1", "memory": "512Mi"},
    },
    "bot": {
        "image": "docker-registry.tools.wmflabs.org/toolforge-php82-sssd-base",
        "cwd": f"{BASE_DIR}/apps/bot",
        "command": ["php", "-f", "cluebot-ng.php"],
        "limits": {"cpu": "0.5", "memory": "2048Mi"},
        "livenessCommand": ["php", "-f", f"{BASE_DIR}/apps/bot/health_check.php"],
    },
    "botng": {
        "image": "docker-registry.tools.wmflabs.org/toolforge-bullseye-standalone:latest",
        "cwd": f"{BASE_DIR}/apps/botng/current",
        "env": {"BOTNG_CFG": f"{BASE_DIR}/.botng.yaml", "BOTNG_LOG": f"{BASE_DIR}/botng.log"},
        "command": [f"{BASE_DIR}/apps/botng/current/botng", "--irc-relay", "--debug",
                    "--processors=500", "--sql-loaders=500", "--http-loaders=500"],
        "ports": [(8118, "TCP")],
        "limits": {"cpu": "0.5", "memory": "1024Mi"},
    },
    "irc-relay": {
        "image": "docker-registry.tools.wmflabs.org/toolforge-python39-sssd-base:latest",
        "cwd": f"{BASE_DIR}/apps/irc_relay",
        "command": ["./relay.py"],
        "ports": [(3334, "UDP")],
        "limits": {"cpu": "0.1", "memory": "100Mi"},
    },
    "grafana-alloy": {
        "image": "docker-registry.tools.wmflabs.org/toolforge-bullseye-standalone:latest",
        "cwd": f"{BASE_DIR}/apps/alloy",
        "command": ["./alloy-boringcrypto-linux-amd64", "run", f"--storage.path={BASE_DIR}/apps/alloy/data", f"{BASE_DIR}/apps/alloy/config.alloy"],
        "limits": {"cpu": "0.1", "memory": "100Mi"},
    }
}


def build_deployment(use_bot_ng):
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "cbng",
            "namespace": f"tool-{TOOL_NAME}"
        },
        "spec": {
            "selector": {"matchLabels": {"cluebot.toolsforge.org/role": "cbng",
                                         "toolforge": "tool",
                                         "toolforge.org/mount-storage": "all"}},
            "template": {
                "metadata": {"labels": {"cluebot.toolsforge.org/role": "cbng",
                                         "toolforge": "tool",
                                         "toolforge.org/mount-storage": "all"}},
                "spec": {
                    "containers": [
                        {**{
                            "name": task_name,
                            "command": [*task["command"]],
                            "env": [
                                {"name": "HOME", "value": BASE_DIR}
                            ] + [
                                {"name": k, "value": v}
                                for k, v in task.get("env", {}).items()
                            ],
                            "image": task["image"],
                            "imagePullPolicy": "Always",
                            "resources": {"limits": task["limits"], "requests": task["limits"]},
                            "volumeMounts": [
                                {"mountPath": "/data/project", "name": "home"}
                            ],
                            "workingDir": task["cwd"],
                        }, **({
                            "livenessProbe": {
                                "timeoutSeconds": 10,
                                "exec": {
                                    "command": task["livenessCommand"]
                                }
                            }
                        } if "livenessCommand" in task else {})}
                        for task_name, task in SUPPORTED_APPS.items()
                        if (
                            task_name == 'core'
                            or
                            (task_name in {'bot', 'irc-relay'} and not use_bot_ng)
                            or
                            (task_name in {'botng', 'grafana-alloy'} and use_bot_ng)
                        )
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


def build_and_apply(use_bot_ng, verbose):
    if deployable := build_deployment(use_bot_ng):
        payload = json.dumps(deployable, indent=4)
        if verbose:
            print('Deploying:')
            print(payload)
        apply_deployable(payload)


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

    print("Successfully deleted:")
    print(p.stdout.decode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--delete", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--botng", action="store_true")
    args = parser.parse_args()

    if args.delete:
        delete(args.deploy)

    if args.deploy:
        build_and_apply(args.botng, args.verbose)


if __name__ == "__main__":
    main()
