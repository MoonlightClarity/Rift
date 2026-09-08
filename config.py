from __future__ import annotations

import os
import sys


# ---------------------------------------------------------------------------
# Base directory
# ---------------------------------------------------------------------------
#
# When running normally from Python:
#
#     BASE_DIR = directory containing config.py
#
# When running as a PyInstaller executable:
#
#     BASE_DIR = directory containing the executable
#
# This keeps external runtime files next to the deployed application
# instead of placing them inside PyInstaller's temporary bundle directory.
# ---------------------------------------------------------------------------

if getattr(
    sys,
    "frozen",
    False,
):

    BASE_DIR = os.path.dirname(
        os.path.abspath(
            sys.executable
        )
    )

else:

    BASE_DIR = os.path.dirname(
        os.path.abspath(
            __file__
        )
    )


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

INPUT_FILE = os.path.join(
    BASE_DIR,
    "today.txt",
)


OUTPUT_FILE = os.path.join(
    BASE_DIR,
    "output.txt",
)


DIAGNOSTIC_DIR = os.path.join(
    BASE_DIR,
    "diagnostic",
)


CONNECT_DIAGNOSTIC_FILE = os.path.join(
    DIAGNOSTIC_DIR,
    "connect_diagnostic.txt",
)


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------

DNS_SERVERS = [
    "8.8.8.8",
    "8.8.4.4",
]


DNS_TIMEOUT = 2.5
DNS_TRIES = 1


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

CONCURRENCY = 1000
QUEUE_MULTIPLIER = 2
LIMIT_PER_HOST = 4


# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------

TOTAL_TIMEOUT = 8.0
CONNECT_TIMEOUT = 4.0
SOCK_CONNECT_TIMEOUT = 4.0
SOCK_READ_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)


ACCEPT_LANGUAGE = (
    "en-US,en;q=0.9"
)


AUTO_DECOMPRESS = True


# 0 means redirects are not followed.
MAX_REDIRECTS = 0


SUCCESS_MIN_STATUS = 200
SUCCESS_MAX_STATUS = 299


# ---------------------------------------------------------------------------
# Response reading
# ---------------------------------------------------------------------------

MAX_READ_BYTES = 128 * 1024
READ_CHUNK_SIZE = 16 * 1024


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

WRITE_BATCH = 100
OUTPUT_FLUSH_IMMEDIATELY = True


CONNECT_DIAGNOSTIC_BATCH = 500


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

PROGRESS_INTERVAL = 2.0


# ---------------------------------------------------------------------------
# Configuration object
# ---------------------------------------------------------------------------

class Config:

    base_dir = BASE_DIR

    input_file = INPUT_FILE
    output_file = OUTPUT_FILE

    diagnostic_dir = DIAGNOSTIC_DIR
    connect_diagnostic_file = (
        CONNECT_DIAGNOSTIC_FILE
    )

    dns_servers = DNS_SERVERS
    dns_timeout = DNS_TIMEOUT
    dns_tries = DNS_TRIES

    concurrency = CONCURRENCY
    queue_multiplier = QUEUE_MULTIPLIER
    limit_per_host = LIMIT_PER_HOST

    total_timeout = TOTAL_TIMEOUT
    connect_timeout = CONNECT_TIMEOUT
    sock_connect_timeout = (
        SOCK_CONNECT_TIMEOUT
    )
    sock_read_timeout = (
        SOCK_READ_TIMEOUT
    )

    user_agent = USER_AGENT
    accept_language = ACCEPT_LANGUAGE
    auto_decompress = AUTO_DECOMPRESS

    max_redirects = MAX_REDIRECTS

    success_min_status = (
        SUCCESS_MIN_STATUS
    )
    success_max_status = (
        SUCCESS_MAX_STATUS
    )

    max_read_bytes = MAX_READ_BYTES
    read_chunk_size = READ_CHUNK_SIZE

    write_batch = WRITE_BATCH
    output_flush_immediately = (
        OUTPUT_FLUSH_IMMEDIATELY
    )

    connect_diagnostic_batch = (
        CONNECT_DIAGNOSTIC_BATCH
    )

    progress_interval = (
        PROGRESS_INTERVAL
    )


CONFIG = Config()