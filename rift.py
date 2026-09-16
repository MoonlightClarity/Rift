from __future__ import annotations

import argparse
import asyncio
import re
import socket
import time
from collections import deque
from dataclasses import dataclass, replace
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp
from aiohttp import resolver

from config import CONFIG, Config


TITLE_PATTERN = re.compile(
    r"<title\b[^>]*>(.*?)</title>",
    re.IGNORECASE | re.DOTALL,
)
TAG_PATTERN = re.compile(r"<[^>]+>", re.DOTALL)
WHITESPACE_PATTERN = re.compile(r"\s+")
SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def _clean_text(value: str, limit: int = 2000) -> str:
    value = unescape(value or "")
    value = WHITESPACE_PATTERN.sub(" ", value).strip()
    return value[:limit]


@dataclass(slots=True)
class PageMetadata:
    title: str = ""
    description: str = ""
    og_title: str = ""
    og_description: str = ""
    h1: str = ""

    def has_any(self) -> bool:
        return any(
            (
                self.title,
                self.description,
                self.og_title,
                self.og_description,
                self.h1,
            )
        )


class _MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.description = ""
        self.og_title = ""
        self.og_description = ""
        self._in_title = False
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
            return
        if tag == "h1" and not self.h1_parts:
            self._in_h1 = True
            return
        if tag != "meta":
            return

        values = {
            str(key).lower(): value
            for key, value in attrs
            if key and value is not None
        }
        key = str(values.get("property") or values.get("name") or "").lower()
        content = _clean_text(str(values.get("content") or ""))
        if not content:
            return
        if key == "description" and not self.description:
            self.description = content
        elif key == "og:title" and not self.og_title:
            self.og_title = content
        elif key == "og:description" and not self.og_description:
            self.og_description = content

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        if self._in_h1:
            self.h1_parts.append(data)


def _extract_metadata(html: str) -> PageMetadata:
    if not html:
        return PageMetadata()

    parser = _MetadataParser()
    try:
        parser.feed(html)
    except Exception:
        pass

    return PageMetadata(
        title=_clean_text(TAG_PATTERN.sub(" ", " ".join(parser.title_parts)), 500),
        description=_clean_text(parser.description, 2000),
        og_title=_clean_text(parser.og_title, 500),
        og_description=_clean_text(parser.og_description, 2000),
        h1=_clean_text(TAG_PATTERN.sub(" ", " ".join(parser.h1_parts)), 1000),
    )


def _extract_title(html: str) -> str:
    metadata = _extract_metadata(html)
    if metadata.title:
        return metadata.title

    match = TITLE_PATTERN.search(html or "")
    if not match:
        return ""
    return _clean_text(TAG_PATTERN.sub(" ", match.group(1)), 500)


def _tsv_field(value: str) -> str:
    return _clean_text(value).replace("\t", " ")


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""

    if not SCHEME_PATTERN.match(url):
        url = "https://" + url

    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in {"http", "https"}:
            return ""

        hostname = parts.hostname
        if not hostname:
            return ""

        hostname = hostname.lower().rstrip(".")
        if not hostname:
            return ""

        try:
            port = parts.port
        except ValueError:
            return ""

        if port is None or (
            (scheme == "http" and port == 80)
            or (scheme == "https" and port == 443)
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


def _candidate_urls(
    value: str,
    http_fallback: bool = True,
) -> list[str]:
    """Return the web probes to try for one domain/URL.

    Rift prefers HTTPS. If HTTPS cannot produce a titled 2xx page and
    HTTP fallback is enabled, it also tries the equivalent HTTP URL.
    This matters for newly registered domains and for ICANN zone-derived
    hostnames that do not yet have working TLS.
    """
    primary = _normalize_url(value)
    if not primary:
        return []

    candidates = [primary]
    parts = urlsplit(primary)

    if http_fallback and parts.scheme == "https":
        fallback = urlunsplit(
            (
                "http",
                parts.netloc,
                parts.path,
                parts.query,
                "",
            )
        )
        if fallback != primary:
            candidates.append(fallback)

    return candidates


def _decode_body(body: bytes, content_type: str) -> str:
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

    # Many newly registered/parked pages omit the HTTP charset but declare
    # it in HTML. Latin-1 is used only as a lossless byte-to-text bridge for
    # finding that declaration; the page is then decoded with the declared
    # charset.
    if not charset:
        prefix = body[:8192].decode("latin-1", errors="ignore")
        meta_match = re.search(
            r"<meta\b[^>]*charset\s*=\s*['\"]?([^\s'\"/>;]+)",
            prefix,
            re.IGNORECASE,
        )
        if not meta_match:
            meta_match = re.search(
                r"<meta\b[^>]*content\s*=\s*['\"][^'\"]*"
                r"charset\s*=\s*([^\s'\"/>;]+)",
                prefix,
                re.IGNORECASE,
            )
        if meta_match:
            charset = meta_match.group(1)

    if not charset:
        charset = "utf-8"

    try:
        return body.decode(charset, errors="replace")
    except (LookupError, UnicodeError):
        return body.decode("utf-8", errors="replace")


class BatchWriter:
    def __init__(
        self,
        path: str | Path,
        batch_size: int,
        flush_immediately: bool = False,
        encoding: str = "utf-8",
    ):
        self.path = Path(path)
        self.batch_size = max(1, int(batch_size))
        self.flush_immediately = flush_immediately
        self.encoding = encoding
        self.queue: deque[str] = deque()
        self._lock = asyncio.Lock()
        self._file = None

    async def start(self, truncate: bool = False) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        mode = "w" if truncate else "a"
        buffering = 1 if self.flush_immediately else -1
        self._file = await asyncio.to_thread(
            self.path.open,
            mode,
            encoding=self.encoding,
            buffering=buffering,
        )

    async def write(self, line: str) -> None:
        async with self._lock:
            self.queue.append(line)
            if len(self.queue) >= self.batch_size or self.flush_immediately:
                await self._flush_locked()

    async def _flush_locked(self) -> None:
        if not self.queue:
            return
        if self._file is None:
            raise RuntimeError("BatchWriter has not been started.")

        data = "".join(self.queue)
        self.queue.clear()
        await asyncio.to_thread(self._file.write, data)

        if self.flush_immediately:
            await asyncio.to_thread(self._file.flush)

    async def flush(self) -> None:
        async with self._lock:
            await self._flush_locked()

    async def close(self) -> None:
        async with self._lock:
            await self._flush_locked()
            if self._file is not None:
                await asyncio.to_thread(self._file.flush)
                await asyncio.to_thread(self._file.close)
                self._file = None


@dataclass(slots=True)
class FetchResult:
    status: int
    url: str
    content_type: str
    html: str


@dataclass(slots=True)
class FetchFailure:
    kind: str
    detail: str


class Scraper:
    """Asynchronous domain/URL metadata probe.

    One ClientSession and one connector are shared across the whole run.
    The previous implementation created a new connector and session for
    every IP attempt, which defeated connection/DNS pooling and made the
    concurrency settings much less effective.
    """

    def __init__(
        self,
        progress_callback=None,
        config: Config | None = None,
    ):
        source_config = config or CONFIG
        self.config = replace(
            source_config,
            dns_servers=list(source_config.dns_servers),
        )
        self.progress_callback = progress_callback
        self.stats = {
            "input": 0,
            "processed": 0,
            "dns_failed": 0,
            "connect_failed": 0,
            "http_failed": 0,
            "live": 0,
            "metadata_success": 0,
            "no_metadata": 0,
            "no_title": 0,
            "title_success": 0,
            "redirects": 0,
            "errors": 0,
            "elapsed": 0.0,
        }
        self.stats_lock = asyncio.Lock()

        self.output_writer = BatchWriter(
            self.config.output_file,
            self.config.write_batch,
            flush_immediately=self.config.output_flush_immediately,
            encoding="utf-8-sig",
        )
        self.diagnostic_writer = BatchWriter(
            self.config.connect_diagnostic_file,
            self.config.connect_diagnostic_batch,
            flush_immediately=self.config.diagnostic_flush_immediately,
        )

        self.started_at = 0.0
        self.session: aiohttp.ClientSession | None = None

    async def _increment(self, key: str, amount: int = 1) -> None:
        async with self.stats_lock:
            self.stats[key] += amount

    async def _snapshot_stats(self) -> dict:
        async with self.stats_lock:
            stats = dict(self.stats)

        stats["elapsed"] = (
            time.monotonic() - self.started_at
            if self.started_at
            else 0.0
        )
        return stats

    async def _publish_stats(self) -> None:
        if self.progress_callback is None:
            return

        stats = await self._snapshot_stats()
        try:
            self.progress_callback(stats)
        except Exception:
            pass

    async def _diagnostic(self, message: str) -> None:
        await self.diagnostic_writer.write(message + "\n")

    async def _read_response_body(
        self,
        response: aiohttp.ClientResponse,
    ) -> bytes:
        body = bytearray()

        while len(body) < self.config.max_read_bytes:
            remaining = self.config.max_read_bytes - len(body)
            chunk = await response.content.read(
                min(self.config.read_chunk_size, remaining)
            )
            if not chunk:
                break
            body.extend(chunk)

        return bytes(body)

    async def _request(
        self,
        url: str,
    ) -> FetchResult | FetchFailure:
        if self.session is None:
            raise RuntimeError("HTTP session has not been initialized.")

        current_url = url
        seen_urls = {current_url}
        redirect_count = 0

        while True:
            try:
                async with self.session.get(
                    current_url,
                    allow_redirects=False,
                ) as response:
                    status = response.status

                    if 300 <= status < 400:
                        location = response.headers.get("Location")
                        if not location:
                            detail = f"status={status} redirect_without_location"
                            await self._diagnostic(
                                f"{url} | {detail}"
                            )
                            return FetchFailure("http", detail)

                        if redirect_count >= self.config.max_redirects:
                            detail = f"status={status} redirect_limit"
                            await self._diagnostic(
                                f"{url} | {detail}"
                            )
                            return FetchFailure("http", detail)

                        next_url = _normalize_url(
                            urljoin(current_url, location)
                        )
                        if not next_url:
                            detail = f"status={status} invalid_redirect"
                            await self._diagnostic(
                                f"{url} | {detail}"
                            )
                            return FetchFailure("http", detail)

                        if next_url in seen_urls:
                            detail = f"status={status} redirect_loop"
                            await self._diagnostic(
                                f"{url} | {detail}"
                            )
                            return FetchFailure("http", detail)

                        seen_urls.add(next_url)
                        current_url = next_url
                        redirect_count += 1
                        await self._increment("redirects")
                        continue

                    if not (
                        self.config.success_min_status
                        <= status
                        <= self.config.success_max_status
                    ):
                        detail = f"status={status}"
                        await self._diagnostic(
                            f"{url} | {detail}"
                        )
                        return FetchFailure("http", detail)

                    content_type = response.headers.get(
                        "Content-Type",
                        "",
                    )
                    body = await self._read_response_body(response)
                    html = _decode_body(body, content_type)

                    return FetchResult(
                        status=status,
                        url=current_url,
                        content_type=content_type,
                        html=html,
                    )

            except asyncio.CancelledError:
                raise
            except aiohttp.ClientConnectorDNSError as exc:
                detail = f"dns_error={type(exc).__name__}:{exc}"
                await self._diagnostic(f"{url} | {detail}")
                return FetchFailure("dns", detail)
            except (asyncio.TimeoutError, aiohttp.ServerTimeoutError) as exc:
                detail = f"timeout={type(exc).__name__}:{exc}"
                await self._diagnostic(f"{url} | {detail}")
                return FetchFailure("connect", detail)
            except (aiohttp.ClientConnectionError, OSError) as exc:
                detail = f"connect_error={type(exc).__name__}:{exc}"
                await self._diagnostic(f"{url} | {detail}")
                return FetchFailure("connect", detail)
            except aiohttp.ClientError as exc:
                detail = f"client_error={type(exc).__name__}:{exc}"
                await self._diagnostic(f"{url} | {detail}")
                return FetchFailure("connect", detail)

    async def _write_result(
        self,
        original_url: str,
        outcome: FetchResult,
        metadata: PageMetadata,
    ) -> None:
        fields = [
            original_url,
            outcome.url,
            str(outcome.status),
            metadata.title,
            metadata.description,
            metadata.og_title,
            metadata.og_description,
            metadata.h1,
        ]
        await self.output_writer.write(
            "\t".join(_tsv_field(value) for value in fields) + "\n"
        )

    async def _process_url(self, original_url: str) -> None:
        try:
            candidates = _candidate_urls(
                original_url,
                http_fallback=self.config.http_fallback,
            )
            if not candidates:
                await self._increment("errors")
                await self._diagnostic(f"{original_url} | invalid_url")
                return

            failures: list[str] = []

            for candidate in candidates:
                outcome = await self._request(candidate)

                if isinstance(outcome, FetchFailure):
                    failures.append(outcome.kind)
                    # HTTP fallback cannot fix a DNS failure for the same host.
                    if outcome.kind == "dns":
                        break
                    continue

                # A successful HTTPS response wins even when it exposes no
                # metadata. HTTP is a transport fallback, not a metadata retry.
                metadata = _extract_metadata(outcome.html)
                await self._increment("live")
                await self._write_result(original_url, outcome, metadata)

                if metadata.has_any():
                    await self._increment("metadata_success")
                    if self.config.log_success_diagnostics:
                        await self._diagnostic(
                            f"{candidate} | status={outcome.status} | "
                            f"final_url={outcome.url} | metadata=yes"
                        )
                else:
                    await self._increment("no_metadata")
                    await self._diagnostic(
                        f"{candidate} | status={outcome.status} | "
                        f"final_url={outcome.url} | no_metadata"
                    )

                if metadata.title:
                    await self._increment("title_success")
                else:
                    await self._increment("no_title")
                return

            if "http" in failures:
                await self._increment("http_failed")
            elif "connect" in failures:
                await self._increment("connect_failed")
            elif "dns" in failures:
                await self._increment("dns_failed")
            else:
                await self._increment("errors")

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._increment("errors")
            try:
                await self._diagnostic(
                    f"{original_url} | unexpected_error="
                    f"{type(exc).__name__}:{exc}"
                )
            except asyncio.CancelledError:
                raise
        finally:
            await self._increment("processed")

    async def _progress_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self.config.progress_interval,
                )
                break
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                raise

            await self._publish_stats()

    async def _worker(self, urls_iter) -> None:
        while True:
            try:
                url = next(urls_iter)
            except StopIteration:
                return
            await self._increment("input")
            await self._process_url(url)

    async def run(self, urls) -> None:
        self.started_at = time.monotonic()

        dns_resolver = None
        connector = None
        progress_task = None
        stop_event = asyncio.Event()
        workers: list[asyncio.Task] = []

        try:
            await self.output_writer.start(truncate=True)
            await self.diagnostic_writer.start(truncate=True)
            await self.output_writer.write(
                "input\tfinal_url\tstatus\ttitle\tdescription\t"
                "og_title\tog_description\th1\n"
            )
            await self._publish_stats()

            dns_resolver = resolver.AsyncResolver(
                nameservers=list(self.config.dns_servers),
                timeout=self.config.dns_timeout,
                tries=max(1, int(self.config.dns_tries)),
            )

            timeout = aiohttp.ClientTimeout(
                total=self.config.total_timeout,
                connect=self.config.connect_timeout,
                sock_connect=self.config.sock_connect_timeout,
                sock_read=self.config.sock_read_timeout,
            )

            connector = aiohttp.TCPConnector(
                resolver=dns_resolver,
                family=socket.AF_INET,
                limit=self.config.concurrency,
                limit_per_host=self.config.limit_per_host,
                ttl_dns_cache=self.config.dns_cache_ttl,
                ssl=False,
            )

            headers = {
                "User-Agent": self.config.user_agent,
                "Accept-Language": self.config.accept_language,
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,*/*;q=0.8"
                ),
            }

            progress_task = asyncio.create_task(
                self._progress_loop(stop_event)
            )

            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                auto_decompress=self.config.auto_decompress,
                headers=headers,
                trust_env=False,
            ) as session:
                self.session = session
                urls_iter = iter(urls)
                worker_count = max(1, int(self.config.concurrency))
                try:
                    worker_count = min(worker_count, len(urls))
                except (TypeError, AttributeError):
                    pass
                workers = [
                    asyncio.create_task(self._worker(urls_iter))
                    for _ in range(worker_count)
                ]
                await asyncio.gather(*workers)

        except asyncio.CancelledError:
            for task in workers:
                if not task.done():
                    task.cancel()
            if workers:
                await asyncio.gather(*workers, return_exceptions=True)
            raise
        except Exception:
            for task in workers:
                if not task.done():
                    task.cancel()
            if workers:
                await asyncio.gather(*workers, return_exceptions=True)
            raise
        finally:
            self.session = None
            stop_event.set()

            if progress_task is not None:
                if not progress_task.done():
                    progress_task.cancel()
                await asyncio.gather(progress_task, return_exceptions=True)

            await self._publish_stats()

            try:
                await self.output_writer.close()
            except Exception:
                pass
            try:
                await self.diagnostic_writer.close()
            except Exception:
                pass
            try:
                close_iter = getattr(urls, "close", None)
                if close_iter is not None:
                    close_iter()
            except Exception:
                pass
            try:
                if connector is not None and not connector.closed:
                    await connector.close()
            except Exception:
                pass
            try:
                if dns_resolver is not None:
                    await dns_resolver.close()
            except Exception:
                pass

        stats = await self._snapshot_stats()
        elapsed = stats["elapsed"]
        rate = stats["processed"] / elapsed if elapsed > 0 else 0.0

        print(
            "\n"
            f"input={stats['input']:,} "
            f"processed={stats['processed']:,} "
            f"live={stats['live']:,} "
            f"metadata_success={stats['metadata_success']:,} "
            f"no_metadata={stats['no_metadata']:,} "
            f"title_success={stats['title_success']:,} "
            f"no_title={stats['no_title']:,} "
            f"dns_failed={stats['dns_failed']:,} "
            f"connect_failed={stats['connect_failed']:,} "
            f"http_failed={stats['http_failed']:,} "
            f"redirects={stats['redirects']:,} "
            f"errors={stats['errors']:,} "
            f"rate={rate:,.1f}/s",
            flush=True,
        )


def _iter_urls(path: str | Path):
    """Stream a domain/URL list in bounded memory.

    Blank lines and comments are ignored. Adjacent duplicates are collapsed,
    which is sufficient for SMET and for the sorted output produced by the
    ICANN compatibility converter without retaining millions of domains in a
    Python set.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")

    previous = None
    with path.open(
        "r",
        encoding="utf-8-sig",
        errors="replace",
    ) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line == previous:
                continue
            previous = line
            yield line


def _load_urls(path: str | Path) -> list[str]:
    """Materialize a small input file; retained for tests and library callers."""
    return list(_iter_urls(path))


def _parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Enrich a domain/URL list with reachable endpoints and passive HTML metadata."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=CONFIG.input_file,
        help="Domain/URL list (default: today.txt next to Rift)",
    )
    parser.add_argument(
        "-o", "--output",
        default=CONFIG.output_file,
        help="TSV output path",
    )
    parser.add_argument(
        "-d", "--diagnostic",
        default=CONFIG.connect_diagnostic_file,
        help="Diagnostic log path",
    )
    parser.add_argument(
        "-c", "--concurrency",
        type=int,
        default=CONFIG.concurrency,
        help="Concurrent workers",
    )
    parser.add_argument(
        "--dns",
        nargs="+",
        default=list(CONFIG.dns_servers),
        help="DNS resolver addresses",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=CONFIG.total_timeout,
        help="Total timeout per request in seconds",
    )
    parser.add_argument(
        "--max-redirects",
        type=int,
        default=CONFIG.max_redirects,
        help="Maximum redirects per probe",
    )
    parser.add_argument(
        "--no-http-fallback",
        action="store_true",
        help="Do not retry failed HTTPS probes over HTTP",
    )
    return parser.parse_args()


def _config_from_args(args) -> Config:
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    diagnostic_path = Path(args.diagnostic).expanduser().resolve()

    if args.concurrency < 1:
        raise ValueError("Concurrency must be at least 1.")
    if args.timeout <= 0:
        raise ValueError("Timeout must be greater than 0.")
    if args.max_redirects < 0:
        raise ValueError("Maximum redirects cannot be negative.")
    if not args.dns:
        raise ValueError("At least one DNS resolver is required.")
    if output_path == input_path:
        raise ValueError("Output file must be different from the input file.")
    if diagnostic_path == input_path:
        raise ValueError("Diagnostic file must be different from the input file.")
    if diagnostic_path == output_path:
        raise ValueError("Diagnostic file must be different from the output file.")

    return replace(
        CONFIG,
        input_file=str(input_path),
        output_file=str(output_path),
        diagnostic_dir=str(diagnostic_path.parent),
        connect_diagnostic_file=str(diagnostic_path),
        concurrency=args.concurrency,
        dns_servers=list(args.dns),
        total_timeout=args.timeout,
        max_redirects=args.max_redirects,
        http_fallback=not args.no_http_fallback,
    )


async def main() -> None:
    args = _parse_args()
    run_config = _config_from_args(args)
    urls = _iter_urls(run_config.input_file)
    scraper = Scraper(config=run_config)
    await scraper.run(urls)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nStopped by user.")
    except Exception as exc:
        raise SystemExit(f"Rift error: {exc}") from exc
