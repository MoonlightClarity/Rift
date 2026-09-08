from __future__ import annotations

import asyncio
import re
import socket
import time
from collections import deque
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp
from aiohttp import resolver

from config import CONFIG


TITLE_PATTERN = re.compile(
    r"<title\b[^>]*>(.*?)</title>",
    re.IGNORECASE | re.DOTALL,
)

TAG_PATTERN = re.compile(
    r"<[^>]+>",
    re.DOTALL,
)

WHITESPACE_PATTERN = re.compile(
    r"\s+"
)


def _extract_title(html: str) -> str:
    if not html:
        return ""

    match = TITLE_PATTERN.search(html)

    if not match:
        return ""

    title = match.group(1)

    title = TAG_PATTERN.sub(
        " ",
        title,
    )

    title = unescape(title)

    title = WHITESPACE_PATTERN.sub(
        " ",
        title,
    ).strip()

    return title


def _normalize_url(url: str) -> str:
    url = url.strip()

    if not url:
        return ""

    if not re.match(
        r"^[a-zA-Z][a-zA-Z0-9+.-]*://",
        url,
    ):
        url = "https://" + url

    try:
        parts = urlsplit(url)

        scheme = parts.scheme.lower()

        if scheme not in {
            "http",
            "https",
        }:
            return ""

        hostname = parts.hostname

        if not hostname:
            return ""

        hostname = hostname.lower()

        try:
            port = parts.port
        except ValueError:
            return ""

        if port is None:
            netloc = hostname

        elif (
            (scheme == "http" and port == 80)
            or
            (scheme == "https" and port == 443)
        ):
            netloc = hostname

        else:
            netloc = f"{hostname}:{port}"

        return urlunsplit(
            (
                scheme,
                netloc,
                parts.path or "/",
                parts.query,
                "",
            )
        )

    except Exception:
        return ""


def _hostname(url: str) -> str:
    try:
        return urlsplit(url).hostname or ""
    except Exception:
        return ""


def _decode_body(
    body: bytes,
    content_type: str,
) -> str:
    if not body:
        return ""

    charset = None

    match = re.search(
        r"charset\s*=\s*['\"]?([^;\s'\"]+)",
        content_type or "",
        re.IGNORECASE,
    )

    if match:
        charset = match.group(1)

    if not charset:
        charset = "utf-8"

    try:
        return body.decode(
            charset,
            errors="replace",
        )
    except (LookupError, UnicodeError):
        return body.decode(
            "utf-8",
            errors="replace",
        )


# ---------------------------------------------------------------------------
# Batch writer
# ---------------------------------------------------------------------------

class BatchWriter:

    def __init__(
        self,
        path: str | Path,
        batch_size: int,
        flush_immediately: bool = False,
    ):
        self.path = Path(path)

        self.batch_size = max(
            1,
            int(batch_size),
        )

        self.flush_immediately = (
            flush_immediately
        )

        self.queue: deque[str] = deque()

        self._lock = asyncio.Lock()
        self._file = None

    async def start(
        self,
        truncate: bool = False,
    ) -> None:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        mode = "w" if truncate else "a"

        self._file = await asyncio.to_thread(
            self.path.open,
            mode,
            encoding="utf-8",
            buffering=1,
        )

    async def write(
        self,
        line: str,
    ) -> None:
        async with self._lock:
            self.queue.append(line)

            if (
                len(self.queue) >= self.batch_size
                or self.flush_immediately
            ):
                await self._flush_locked()

    async def _flush_locked(self) -> None:
        if not self.queue:
            return

        if self._file is None:
            raise RuntimeError(
                "BatchWriter has not been started."
            )

        lines = list(self.queue)
        self.queue.clear()

        data = "".join(lines)

        await asyncio.to_thread(
            self._file.write,
            data,
        )

        if self.flush_immediately:
            await asyncio.to_thread(
                self._file.flush,
            )

    async def flush(self) -> None:
        async with self._lock:
            await self._flush_locked()

    async def close(self) -> None:
        async with self._lock:
            await self._flush_locked()

            if self._file is not None:
                await asyncio.to_thread(
                    self._file.flush
                )

                await asyncio.to_thread(
                    self._file.close
                )

                self._file = None


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------

class GoogleDNSResolver:

    def __init__(
        self,
        servers: list[str],
        timeout: float,
        tries: int,
    ):
        self.servers = list(servers)

        self.timeout = timeout

        self.tries = max(
            1,
            int(tries),
        )

        self._resolvers = [
            resolver.AsyncResolver(
                nameservers=[server],
                timeout=timeout,
                tries=self.tries,
            )
            for server in self.servers
        ]

    async def resolve(
        self,
        hostname: str,
    ) -> list[str]:

        for dns_index, dns_resolver in enumerate(
            self._resolvers
        ):
            try:
                results = await asyncio.wait_for(
                    dns_resolver.resolve(
                        hostname,
                        443,
                        socket.AF_INET,
                    ),
                    timeout=self.timeout,
                )

                addresses = []

                for result in results:
                    ip = result["host"]

                    if ip not in addresses:
                        addresses.append(ip)

                if addresses:
                    return addresses

            except asyncio.CancelledError:
                raise

            except (
                asyncio.TimeoutError,
                aiohttp.ClientError,
                OSError,
            ):
                if (
                    dns_index + 1
                    >= len(self._resolvers)
                ):
                    return []

                continue

        return []

    async def close(self) -> None:
        for dns_resolver in self._resolvers:
            try:
                await dns_resolver.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Selected IP resolver
# ---------------------------------------------------------------------------

class SelectedIPResolver:

    def __init__(
        self,
        ip: str,
    ):
        self.ip = ip

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: int = 0,
    ):
        return [
            {
                "hostname": host,
                "host": self.ip,
                "port": port,
                "family": socket.AF_INET,
                "proto": 0,
                "flags": 0,
            }
        ]

    async def close(self):
        return None


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class Scraper:

    def __init__(
        self,
        progress_callback=None,
    ):
        self.progress_callback = (
            progress_callback
        )

        self.stats = {
            "input": 0,
            "processed": 0,
            "dns_failed": 0,
            "connect_failed": 0,
            "http_failed": 0,
            "live": 0,
            "no_title": 0,
            "title_success": 0,
            "redirects": 0,
            "errors": 0,
            "elapsed": 0.0,
        }

        self.stats_lock = asyncio.Lock()

        self.output_writer = BatchWriter(
            CONFIG.output_file,
            CONFIG.write_batch,
            flush_immediately=(
                CONFIG.output_flush_immediately
            ),
        )

        self.diagnostic_writer = BatchWriter(
            CONFIG.connect_diagnostic_file,
            CONFIG.connect_diagnostic_batch,
            flush_immediately=True,
        )

        # IMPORTANT:
        # Do NOT create GoogleDNSResolver here.
        #
        # aiohttp AsyncResolver requires a running asyncio
        # event loop. It is therefore created inside run().
        self.dns: GoogleDNSResolver | None = None

        self.started_at = 0.0

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    async def _increment(
        self,
        key: str,
        amount: int = 1,
    ) -> None:
        async with self.stats_lock:
            self.stats[key] += amount

    async def _snapshot_stats(self) -> dict:
        async with self.stats_lock:
            stats = dict(self.stats)

        elapsed = (
            time.monotonic()
            - self.started_at
            if self.started_at
            else 0.0
        )

        stats["elapsed"] = elapsed

        return stats

    async def _publish_stats(self) -> None:
        if self.progress_callback is None:
            return

        stats = await self._snapshot_stats()

        try:
            self.progress_callback(stats)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Diagnostic
    # ------------------------------------------------------------------

    async def _diagnostic(
        self,
        message: str,
    ) -> None:
        await self.diagnostic_writer.write(
            message + "\n"
        )

    # ------------------------------------------------------------------
    # HTTP request
    # ------------------------------------------------------------------

    async def _request(
        self,
        url: str,
        ip: str,
    ) -> dict | None:

        timeout = aiohttp.ClientTimeout(
            total=CONFIG.total_timeout,
            connect=CONFIG.connect_timeout,
            sock_connect=CONFIG.sock_connect_timeout,
            sock_read=CONFIG.sock_read_timeout,
        )

        selected_resolver = SelectedIPResolver(ip)

        connector = aiohttp.TCPConnector(
            resolver=selected_resolver,
            family=socket.AF_INET,
            limit=CONFIG.concurrency,
            limit_per_host=CONFIG.limit_per_host,
            ttl_dns_cache=0,
            ssl=False,
            enable_cleanup_closed=True,
        )

        headers = {
            "User-Agent": CONFIG.user_agent,
            "Accept-Language": CONFIG.accept_language,
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "*/*;q=0.8"
            ),
        }

        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                auto_decompress=CONFIG.auto_decompress,
                headers=headers,
                trust_env=False,
            ) as session:

                current_url = url
                redirect_count = 0

                while True:
                    try:
                        async with session.get(
                            current_url,
                            allow_redirects=False,
                        ) as response:

                            status = response.status

                            # Redirects are intentionally not followed
                            # when MAX_REDIRECTS == 0.
                            if (
                                300
                                <= status
                                < 400
                            ):
                                location = (
                                    response.headers.get(
                                        "Location"
                                    )
                                )

                                if not location:
                                    await self._diagnostic(
                                        f"{url} | "
                                        f"ip={ip} | "
                                        f"status={status} | "
                                        f"redirect_without_location"
                                    )

                                    return None

                                if (
                                    redirect_count
                                    >= CONFIG.max_redirects
                                ):
                                    await self._diagnostic(
                                        f"{url} | "
                                        f"ip={ip} | "
                                        f"redirect_limit"
                                    )

                                    return None

                                next_url = _normalize_url(
                                    urljoin(
                                        current_url,
                                        location,
                                    )
                                )

                                if not next_url:
                                    await self._diagnostic(
                                        f"{url} | "
                                        f"ip={ip} | "
                                        f"invalid_redirect"
                                    )

                                    return None

                                current_url = next_url
                                redirect_count += 1

                                await self._increment(
                                    "redirects"
                                )

                                continue

                            if not (
                                CONFIG.success_min_status
                                <= status
                                <= CONFIG.success_max_status
                            ):
                                await self._increment(
                                    "http_failed"
                                )

                                await self._diagnostic(
                                    f"{url} | "
                                    f"ip={ip} | "
                                    f"status={status}"
                                )

                                return None

                            content_type = (
                                response.headers.get(
                                    "Content-Type",
                                    "",
                                )
                            )

                            body = bytearray()

                            while True:
                                chunk = await response.content.read(
                                    CONFIG.read_chunk_size
                                )

                                if not chunk:
                                    break

                                remaining = (
                                    CONFIG.max_read_bytes
                                    - len(body)
                                )

                                if remaining <= 0:
                                    break

                                body.extend(
                                    chunk[:remaining]
                                )

                                if (
                                    len(body)
                                    >= CONFIG.max_read_bytes
                                ):
                                    break

                            html = _decode_body(
                                bytes(body),
                                content_type,
                            )

                            return {
                                "status": status,
                                "url": current_url,
                                "ip": ip,
                                "content_type": content_type,
                                "html": html,
                            }

                    except asyncio.CancelledError:
                        raise

                    except asyncio.TimeoutError:
                        await self._increment(
                            "connect_failed"
                        )

                        await self._diagnostic(
                            f"{url} | "
                            f"ip={ip} | "
                            f"timeout"
                        )

                        return None

                    except (
                        aiohttp.ClientError,
                        OSError,
                    ) as exc:
                        await self._increment(
                            "connect_failed"
                        )

                        await self._diagnostic(
                            f"{url} | "
                            f"ip={ip} | "
                            f"error="
                            f"{type(exc).__name__}:"
                            f"{exc}"
                        )

                        return None

        except asyncio.CancelledError:
            raise

        finally:
            try:
                await selected_resolver.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Process URL
    # ------------------------------------------------------------------

    async def _process_url(
        self,
        original_url: str,
        semaphore: asyncio.Semaphore,
    ) -> None:

        try:
            async with semaphore:

                url = _normalize_url(
                    original_url
                )

                if not url:
                    await self._increment(
                        "errors"
                    )

                    await self._diagnostic(
                        f"{original_url} | invalid_url"
                    )

                    return

                hostname = _hostname(url)

                if not hostname:
                    await self._increment(
                        "errors"
                    )

                    await self._diagnostic(
                        f"{url} | invalid_hostname"
                    )

                    return

                if self.dns is None:
                    raise RuntimeError(
                        "DNS resolver has not been initialized."
                    )

                addresses = await self.dns.resolve(
                    hostname
                )

                if not addresses:
                    await self._increment(
                        "dns_failed"
                    )

                    await self._diagnostic(
                        f"{url} | dns_failed"
                    )

                    return

                for ip in addresses:

                    result = await self._request(
                        url,
                        ip,
                    )

                    if result is None:
                        continue

                    await self._increment(
                        "live"
                    )

                    final_url = result["url"]
                    status = result["status"]
                    html = result["html"]

                    title = _extract_title(
                        html
                    )

                    if not title:
                        await self._increment(
                            "no_title"
                        )

                        await self._diagnostic(
                            f"{url} | "
                            f"ip={ip} | "
                            f"status={status} | "
                            f"final_url={final_url} | "
                            f"no_title"
                        )

                        return

                    await self.output_writer.write(
                        f"{final_url}\t{title}\n"
                    )

                    await self._increment(
                        "title_success"
                    )

                    await self._diagnostic(
                        f"{url} | "
                        f"ip={ip} | "
                        f"status={status} | "
                        f"final_url={final_url} | "
                        f"title={title}"
                    )

                    return

                await self._increment(
                    "http_failed"
                )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            await self._increment(
                "errors"
            )

            try:
                await self._diagnostic(
                    f"{original_url} | "
                    f"unexpected_error="
                    f"{type(exc).__name__}:"
                    f"{exc}"
                )
            except asyncio.CancelledError:
                raise

        finally:
            await self._increment(
                "processed"
            )

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    async def _progress_loop(
        self,
        stop_event: asyncio.Event,
    ) -> None:

        while not stop_event.is_set():

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=CONFIG.progress_interval,
                )

                break

            except asyncio.TimeoutError:
                pass

            except asyncio.CancelledError:
                raise

            await self._publish_stats()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(
        self,
        urls: list[str],
    ) -> None:

        self.started_at = time.monotonic()

        # IMPORTANT:
        # This constructor must execute while an asyncio loop
        # is already running.
        self.dns = GoogleDNSResolver(
            servers=CONFIG.dns_servers,
            timeout=CONFIG.dns_timeout,
            tries=CONFIG.dns_tries,
        )

        # Create output files immediately when scan starts.
        await self.output_writer.start(
            truncate=True
        )

        await self.diagnostic_writer.start(
            truncate=True
        )

        await self._increment(
            "input",
            len(urls),
        )

        await self._publish_stats()

        semaphore = asyncio.Semaphore(
            CONFIG.concurrency
        )

        stop_event = asyncio.Event()

        progress_task = asyncio.create_task(
            self._progress_loop(
                stop_event
            )
        )

        current_tasks: set[asyncio.Task] = set()

        try:
            batch_size = (
                CONFIG.concurrency
                * CONFIG.queue_multiplier
            )

            for start in range(
                0,
                len(urls),
                batch_size,
            ):

                if stop_event.is_set():
                    break

                batch = urls[
                    start:start + batch_size
                ]

                if not batch:
                    continue

                current_tasks = {
                    asyncio.create_task(
                        self._process_url(
                            url,
                            semaphore,
                        )
                    )
                    for url in batch
                }

                try:
                    await asyncio.gather(
                        *current_tasks
                    )

                except asyncio.CancelledError:
                    for task in current_tasks:
                        if not task.done():
                            task.cancel()

                    if current_tasks:
                        await asyncio.gather(
                            *current_tasks,
                            return_exceptions=True,
                        )

                    raise

                finally:
                    current_tasks.clear()

                await self._publish_stats()

        except asyncio.CancelledError:

            for task in current_tasks:
                if not task.done():
                    task.cancel()

            if current_tasks:
                await asyncio.gather(
                    *current_tasks,
                    return_exceptions=True,
                )

            raise

        finally:

            stop_event.set()

            if not progress_task.done():
                progress_task.cancel()

            await asyncio.gather(
                progress_task,
                return_exceptions=True,
            )

            # Publish final statistics before shutdown.
            await self._publish_stats()

            try:
                await self.output_writer.close()
            except Exception:
                pass

            try:
                await self.diagnostic_writer.close()
            except Exception:
                pass

            if self.dns is not None:
                try:
                    await self.dns.close()
                except Exception:
                    pass

                self.dns = None

        stats = await self._snapshot_stats()

        elapsed = stats["elapsed"]

        rate = (
            stats["processed"] / elapsed
            if elapsed > 0
            else 0.0
        )

        print(
            "\n"
            f"input={stats['input']:,} "
            f"processed={stats['processed']:,} "
            f"live={stats['live']:,} "
            f"title_success="
            f"{stats['title_success']:,} "
            f"no_title="
            f"{stats['no_title']:,} "
            f"dns_failed="
            f"{stats['dns_failed']:,} "
            f"connect_failed="
            f"{stats['connect_failed']:,} "
            f"http_failed="
            f"{stats['http_failed']:,} "
            f"redirects="
            f"{stats['redirects']:,} "
            f"errors="
            f"{stats['errors']:,} "
            f"rate="
            f"{rate:,.1f}/s",
            flush=True,
        )


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

def _load_urls(
    path: str | Path,
) -> list[str]:

    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(
            f"Input file not found: {path}"
        )

    urls = []

    with path.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as fh:

        for line in fh:
            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            urls.append(line)

    return urls


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:

    urls = _load_urls(
        CONFIG.input_file
    )

    if not urls:
        print(
            "No URLs found in "
            f"{CONFIG.input_file}"
        )
        return

    scraper = Scraper()

    await scraper.run(urls)


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print(
            "\nStopped by user."
        )