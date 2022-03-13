#!/usr/bin/env python3
"""
Execution wrapper for k8s based tasks on toolsforge.

Replaces previous run_xxx.sh / update_node.sh.
"""
import argparse
import logging
import os
import os.path
import socket
import sys
import time

import pymysql

logger = logging.getLogger(__name__)


def get_pod_ip():
    ip = socket.gethostbyname(socket.gethostname())
    assert ip != "127.0.0.1"
    logger.info(f"Discovered pod ip: {ip}")
    return ip


def update_node(node_endpoint, task_name):
    normalized_task_name = task_name.replace("-", "_")
    replica_cfg = os.path.expanduser("~/replica.my.cnf")
    with pymysql.connect(
        read_default_file=replica_cfg, host="tools-db", database="s52585__cb"
    ) as connection:
        logger.info(f"Updating node table {normalized_task_name} -> {node_endpoint}")
        with connection.cursor() as cursor:
            cursor.execute(
                "REPLACE INTO cluster_node VALUES (%s, %s)",
                (node_endpoint, normalized_task_name),
            )
        connection.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-name", action="append")
    args = parser.parse_args()

    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)-15s %(levelname)s:%(name)s:%(message)s",
    )

    print(args)

    for task_name in args.task_name:
        update_node(get_pod_ip(), task_name)

    # Wait until the pod is torn down
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
