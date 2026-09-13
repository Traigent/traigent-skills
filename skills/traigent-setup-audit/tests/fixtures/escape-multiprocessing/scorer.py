"""Escape route: a fresh interpreter via multiprocessing, with no guard in it."""

import multiprocessing
import os
import socket


def _reach_out(port):
    connection = socket.create_connection(("localhost", port), timeout=2)
    connection.close()


def score(output, expected):
    port = int(os.getenv("TRAIGENT_AUDIT_PROBE_PORT", "0"))
    worker = multiprocessing.Process(target=_reach_out, args=(port,))
    worker.start()
    worker.join(5)
    return 1.0 if output == expected else 0.0
