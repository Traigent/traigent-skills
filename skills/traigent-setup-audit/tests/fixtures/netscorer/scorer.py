"""Fixture scorer: opens a socket while scoring, so the guard must refuse it.

Pure standard library. Executed by `scorer_probe.py` only, which installs the
network guard before this module is loaded.
"""

import socket


def score(output, expected):
    connection = socket.create_connection(("localhost", 9), timeout=1)
    connection.close()
    return 1.0 if output == expected else 0.0
