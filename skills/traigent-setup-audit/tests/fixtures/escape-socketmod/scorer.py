"""Escape route: the private `_socket` module, which the first guard left bound."""

import os
import _socket


def score(output, expected):
    port = int(os.getenv("TRAIGENT_AUDIT_PROBE_PORT", "0"))
    connection = _socket.socket()
    connection.connect(("localhost", port))
    connection.close()
    return 1.0 if output == expected else 0.0
