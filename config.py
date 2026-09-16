from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field


# Runtime files live next to the source tree when running from Python and next
# to the executable when packaged with PyInstaller. Rift is intentionally a
# portable local utility rather than an installed service.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@dataclass(slots=True)
class Config:
    base_dir: str = BASE_DIR

    input_file: str = os.path.join(BASE_DIR, "today.txt")
    output_file: str = os.path.join(BASE_DIR, "results.tsv")
    diagnostic_dir: str = os.path.join(BASE_DIR, "diagnostic")
    connect_diagnostic_file: str = os.path.join(
        BASE_DIR,
        "diagnostic",
        "connect_diagnostic.txt",
    )

    dns_servers: list[str] = field(
        default_factory=lambda: ["8.8.8.8", "8.8.4.4"]
    )
    dns_timeout: float = 2.5
    dns_tries: int = 1

    concurrency: int = 1000
    limit_per_host: int = 4

    total_timeout: float = 8.0
    connect_timeout: float = 4.0
    sock_connect_timeout: float = 4.0
    sock_read_timeout: float = 5.0

    user_agent: str = (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
    accept_language: str = "en-US,en;q=0.9"
    auto_decompress: bool = True

    # Newly registered domains commonly redirect from apex to www or HTTP to
    # HTTPS. Keep the chain bounded so broken redirect loops cannot run away.
    max_redirects: int = 5

    # If HTTPS cannot produce a titled successful response, also try HTTP.
    http_fallback: bool = True

    # Reuse DNS answers briefly during redirects and retries.
    dns_cache_ttl: int = 300

    success_min_status: int = 200
    success_max_status: int = 299

    max_read_bytes: int = 128 * 1024
    read_chunk_size: int = 16 * 1024

    write_batch: int = 100
    output_flush_immediately: bool = False
    connect_diagnostic_batch: int = 500
    diagnostic_flush_immediately: bool = False
    log_success_diagnostics: bool = False

    progress_interval: float = 2.0


CONFIG = Config()
