"""Wire message identifiers.

One TCP connection carries both directions:

    controller -> agent : HELLO, PING, TRANSFER_*, INPUT, STREAM_*, SESSION_KILL
    agent -> controller : HELLO_ACK, PONG, TRANSFER_ACK, RESTORE_RESULT, FRAME, LOG
"""
from __future__ import annotations

from enum import IntEnum


class Msg(IntEnum):
    # handshake / liveness
    HELLO = 1
    HELLO_ACK = 2
    PING = 3
    PONG = 4

    # state transfer
    TRANSFER_BEGIN = 10
    TRANSFER_CHUNK = 11
    TRANSFER_END = 12
    TRANSFER_ACK = 13
    RESTORE_RESULT = 14

    # remote UI
    STREAM_START = 20
    STREAM_STOP = 21
    FRAME = 22
    INPUT = 23
    RESIZE = 24

    # session lifecycle
    SESSION_KILL = 30
    SESSION_GONE = 31

    LOG = 40
    ERROR = 41
