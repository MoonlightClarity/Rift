from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from Icann_file_compatibility_cleaner import clean_zone_file
from config import Config
from rift import (
    FetchResult,
    Scraper,
    _candidate_urls,
    _extract_metadata,
    _extract_title,
    _load_urls,
    _normalize_url,
)


class CoreHelpersTests(unittest.TestCase):
    def test_normalize_domain(self):
        self.assertEqual(
            _normalize_url("Example.COM"),
            "https://example.com/",
        )

    def test_title_extraction(self):
        self.assertEqual(
            _extract_title("<title> A &amp; <b>B</b> </title>"),
            "A & B",
        )

    def test_passive_metadata_extraction(self):
        html = """
        <html>
          <head>
            <title>Primary &amp; Title</title>
            <meta name="description" content="A useful description">
            <meta property="og:title" content="Social title">
            <meta property="og:description" content="Social description">
          </head>
          <body><h1>First <span>heading</span></h1></body>
        </html>
        """
        metadata = _extract_metadata(html)
        self.assertEqual(metadata.title, "Primary & Title")
        self.assertEqual(metadata.description, "A useful description")
        self.assertEqual(metadata.og_title, "Social title")
        self.assertEqual(metadata.og_description, "Social description")
        self.assertEqual(metadata.h1, "First heading")
        self.assertTrue(metadata.has_any())

    def test_https_then_http_candidates(self):
        self.assertEqual(
            _candidate_urls("example.com", http_fallback=True),
            ["https://example.com/", "http://example.com/"],
        )
        self.assertEqual(
            _candidate_urls("example.com", http_fallback=False),
            ["https://example.com/"],
        )

    def test_loader_handles_bom_comments_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "domains.txt"
            path.write_text(
                "\ufeffexample.com\n# comment\nexample.com\npython.org\n",
                encoding="utf-8",
            )
            self.assertEqual(
                _load_urls(path),
                ["example.com", "python.org"],
            )


class IcannCompatibilityTests(unittest.TestCase):
    def test_zone_file_cleaning(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "zone.txt"
            output = Path(tmp) / "domains.txt"
            source.write_text(
                "\ufefforg. 3600 IN SOA a0.org. hostmaster.org. 1 2 3 4 5\n"
                "org. 3600 IN NS a0.org.\n"
                "example.org. 3600 IN NS ns1.example.org.\n"
                "example.org. 3600 IN NS ns2.example.org.\n"
                "ns1.example.org. 3600 IN A 192.0.2.1\n"
                "HASHED.org. 3600 IN NSEC3 1 0 0 - NEXT A NS SOA\n"
                "other.org. 3600 IN NS ns1.other.net.\n"
                "truncated-final-record",
                encoding="utf-8",
            )
            stats = clean_zone_file(source, output)
            self.assertEqual(stats["zone_apex"], "org")
            self.assertEqual(stats["output_count"], 2)
            self.assertEqual(stats["duplicates"], 1)
            self.assertEqual(stats["rejected"], 1)
            self.assertEqual(
                output.read_text(encoding="utf-8").splitlines(),
                ["example.org", "other.org"],
            )


class _TestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/metadata")
            self.end_headers()
            return

        if self.path == "/loop":
            self.send_response(302)
            self.send_header("Location", "/loop")
            self.end_headers()
            return

        if self.path == "/empty":
            body = b"<html><body><p>Reachable but intentionally unlabeled.</p></body></html>"
        elif self.path == "/description-only":
            body = (
                b'<html><head><meta name="description" content="Description only">'
                b"</head><body></body></html>"
            )
        else:
            body = (
                b"<html><head><title>Fallback worked</title>"
                b'<meta name="description" content="Controlled description">'
                b'<meta property="og:title" content="Controlled OG title">'
                b'<meta property="og:description" content="Controlled OG description">'
                b"</head><body><h1>Controlled heading</h1></body></html>"
            )

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def _run_local_scan(paths: list[str]):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    tmp = tempfile.TemporaryDirectory()
    output = Path(tmp.name) / "out.tsv"
    diagnostic = Path(tmp.name) / "diag.txt"
    config = Config(
        output_file=str(output),
        connect_diagnostic_file=str(diagnostic),
        diagnostic_dir=str(Path(tmp.name)),
        concurrency=4,
        http_fallback=True,
        max_redirects=5,
    )
    port = server.server_address[1]
    urls = [f"https://127.0.0.1:{port}{path}" for path in paths]

    async def run_test():
        scraper = Scraper(config=config)
        await scraper.run(iter(urls))
        return await scraper._snapshot_stats()

    try:
        stats = asyncio.run(run_test())
        lines = output.read_text(encoding="utf-8-sig").splitlines()
        diagnostics = diagnostic.read_text(encoding="utf-8").splitlines()
        return stats, lines, diagnostics, urls
    finally:
        server.shutdown()
        server.server_close()
        tmp.cleanup()


class NetworkIntegrationTests(unittest.TestCase):
    def test_https_fallback_redirect_and_rich_metadata(self):
        stats, lines, _diagnostics, urls = _run_local_scan([""])

        self.assertEqual(stats["live"], 1)
        self.assertEqual(stats["metadata_success"], 1)
        self.assertEqual(stats["title_success"], 1)
        self.assertEqual(stats["redirects"], 1)
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            lines[0],
            "input\tfinal_url\tstatus\ttitle\tdescription\tog_title\tog_description\th1",
        )
        columns = lines[1].split("\t")
        self.assertEqual(columns[0], urls[0])
        self.assertTrue(columns[1].startswith("http://127.0.0.1:"))
        self.assertEqual(columns[2], "200")
        self.assertEqual(columns[3], "Fallback worked")
        self.assertEqual(columns[4], "Controlled description")
        self.assertEqual(columns[5], "Controlled OG title")
        self.assertEqual(columns[6], "Controlled OG description")
        self.assertEqual(columns[7], "Controlled heading")

    def test_description_without_title_is_still_enriched(self):
        stats, lines, _diagnostics, _urls = _run_local_scan(["/description-only"])
        self.assertEqual(stats["live"], 1)
        self.assertEqual(stats["metadata_success"], 1)
        self.assertEqual(stats["title_success"], 0)
        self.assertEqual(stats["no_title"], 1)
        self.assertEqual(lines[1].split("\t")[4], "Description only")

    def test_live_page_without_metadata_is_preserved(self):
        stats, lines, diagnostics, _urls = _run_local_scan(["/empty"])
        self.assertEqual(stats["live"], 1)
        self.assertEqual(stats["metadata_success"], 0)
        self.assertEqual(stats["no_metadata"], 1)
        self.assertEqual(stats["no_title"], 1)
        self.assertEqual(len(lines), 2)
        self.assertEqual(len(lines[1].split("\t")), 8)
        self.assertTrue(any("no_metadata" in line for line in diagnostics))

    def test_https_success_does_not_fall_back_for_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.tsv"
            diagnostic = Path(tmp) / "diag.txt"
            config = Config(
                output_file=str(output),
                connect_diagnostic_file=str(diagnostic),
                diagnostic_dir=str(Path(tmp)),
                http_fallback=True,
            )

            async def run_test():
                scraper = Scraper(config=config)
                await scraper.output_writer.start(truncate=True)
                await scraper.diagnostic_writer.start(truncate=True)
                calls = []

                async def fake_request(url):
                    calls.append(url)
                    if url.startswith("https://"):
                        return FetchResult(
                            status=200,
                            url=url,
                            content_type="text/html",
                            html="<html><body>no metadata</body></html>",
                        )
                    return FetchResult(
                        status=200,
                        url=url,
                        content_type="text/html",
                        html="<html><title>HTTP metadata</title></html>",
                    )

                scraper._request = fake_request
                try:
                    await scraper._process_url("example.org")
                    stats = await scraper._snapshot_stats()
                finally:
                    await scraper.output_writer.close()
                    await scraper.diagnostic_writer.close()
                return calls, stats

            calls, stats = asyncio.run(run_test())
            self.assertEqual(calls, ["https://example.org/"])
            self.assertEqual(stats["live"], 1)
            self.assertEqual(stats["no_metadata"], 1)
            self.assertEqual(stats["title_success"], 0)

    def test_redirect_loop_is_classified_as_http_failure(self):
        stats, lines, diagnostics, _urls = _run_local_scan(["/loop"])
        self.assertEqual(stats["live"], 0)
        self.assertEqual(stats["http_failed"], 1)
        self.assertEqual(len(lines), 1)
        self.assertTrue(any("redirect_loop" in line for line in diagnostics))


if __name__ == "__main__":
    unittest.main()
