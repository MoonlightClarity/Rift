# Rift

Rift is a local asynchronous utility for enriching large domain lists with live web metadata.

> This is my first project. I am still open-sourcing it in the hope that someone can use it. It will not likely be updated much, if at all.

Its primary workflow is deliberately narrow:

```text
domain list -> DNS/web probe -> structured TSV metadata
```

Rift was originally built around newly registered domain data such as the SMET NRD `today.txt` feed. It can also ingest ICANN-style DNS zone exports after conversion with the included compatibility cleaner.

## What Rift does

For each input domain or URL, Rift:

1. prefers HTTPS;
2. resolves and connects asynchronously;
3. follows a bounded redirect chain;
4. reads only a bounded amount of the response body;
5. extracts passive HTML metadata from the same bounded response body: title, meta description, Open Graph title/description, and the first H1;
6. falls back to HTTP only when HTTPS fails to produce a successful page;
7. records the original input together with the final live URL, status, and whatever passive metadata was available.

The primary output is UTF-8 tab-separated text with a header. Rift writes a UTF-8 BOM for better compatibility with Windows spreadsheet and shell tooling:

```text
input	final_url	status	title	description	og_title	og_description	h1
example.com	https://example.com/	200	Example Domain	...	...	...	Example Domain
```

Preserving the original input is intentional. A newly registered domain may redirect to another hostname, and an enrichment result should remain traceable to the domain that was scanned.

Reachable 2xx pages are preserved even when they expose no title or other passive metadata. Failures and unusual responses are written to the diagnostic file.

## Input

### SMET / plain domain lists

SMET-style files are directly usable. They contain one domain per line:

```text
example.com
example.org
example.net
```

Full HTTP/HTTPS URLs are also accepted. Blank lines, comments beginning with `#`, a UTF-8 BOM, and adjacent duplicate lines are handled by the streaming loader.

The SMET NRD daily feed is published at:

```text
https://smet.cz/nrd/data/today.txt
```

Rift does not depend on that URL specifically; any compatible domain-per-line text file can be supplied.

### ICANN zone exports

ICANN-style DNS zone exports use a different input shape. Convert them first with:

```text
python Icann_file_compatibility_cleaner.py input.zone cleaned.txt
```

The compatibility converter streams the zone file, detects the zone apex from SOA, keeps delegated-domain NS owners, collapses repeated NS rows, and writes a Rift-compatible bare-domain list. DNSSEC records, glue A/AAAA records, the zone apex, and other non-delegation owners are skipped. It assumes records are grouped by owner name, as in the ICANN/CZDS TLD-zone exports it was built for; that assumption lets it process very large zones without holding millions of names in memory.

It is intentionally an ICANN/CZDS TLD-zone compatibility converter, not a general-purpose BIND master-file parser.

## Installation

Python 3.13 or newer is recommended.

```text
pip install -r requirements.txt
```

Runtime dependencies are limited to `aiohttp` and `aiodns`.

## Running Rift

Basic use:

```text
python rift.py today.txt
```

Explicit paths:

```text
python rift.py today.txt -o results.tsv -d diagnostic.txt
```

Useful runtime controls:

```text
python rift.py today.txt \
    -o results.tsv \
    -d diagnostic.txt \
    --concurrency 500 \
    --timeout 8 \
    --max-redirects 5
```

On Windows PowerShell, the same command can be entered on one line.

Available command-line options can always be inspected with:

```text
python rift.py --help
```

Important options include:

- `-o`, `--output`: TSV result file;
- `-d`, `--diagnostic`: diagnostic log;
- `-c`, `--concurrency`: concurrent workers;
- `--dns`: one or more DNS resolver addresses;
- `--timeout`: total request timeout;
- `--max-redirects`: redirect limit;
- `--no-http-fallback`: disable HTTPS-to-HTTP fallback.

`config.py` supplies defaults for advanced behavior. Command-line values are copied into a per-run configuration snapshot; running a scan does not mutate global configuration state.

## Architecture

The network enrichment pipeline lives in `rift.py`.

A scan uses one shared `aiohttp` session and connector. A fixed worker pool continuously consumes the input list, so a handful of slow hosts do not block an entire request batch.

The enrichment pipeline provides:

- asynchronous concurrent requests;
- configurable DNS resolvers;
- IPv4 probing;
- shared connection and DNS caching;
- HTTPS-first probing with optional HTTP fallback;
- bounded redirect following;
- bounded response reads;
- basic HTTP and HTML charset handling;
- passive extraction of title, meta description, Open Graph title/description, and first H1;
- streaming input with bounded memory;
- batched output and diagnostics;
- periodic progress statistics;
- cancellation through `Ctrl+C`.

## Network behavior

Rift is designed for broad lightweight metadata collection from heterogeneous newly registered domains, not browser-grade rendering.

Important limitations and choices:

- JavaScript is not executed.
- Only returned HTML is inspected.
- TLS certificate verification is disabled so certificate problems do not automatically exclude a host from metadata collection.
- IPv4 is used.
- A page must return a configured successful HTTP status to appear in primary output; metadata fields may be blank.
- Redirects may move requests to another hostname; the final URL is recorded while the original input is retained.
- Response reads are bounded, so Rift does not download entire large pages simply to obtain lightweight metadata.

## Diagnostics

Failures are written separately from successful enrichment results. Diagnostic entries distinguish common categories such as:

- DNS failures;
- connection/TLS failures;
- timeouts;
- non-successful HTTP statuses;
- redirect problems;
- successful pages with no passive metadata;
- unexpected internal errors.

Successful requests are not logged to diagnostics by default, keeping large runs substantially smaller.

## Tests

Run the regression suite with:

```text
python -m unittest discover -s tests -v
```

The tests cover URL normalization, passive metadata extraction, UTF-8 BOM handling, adjacent duplicate input removal, ICANN/CZDS delegation conversion, HTTPS-to-HTTP fallback, redirect loops, no-metadata live pages, and the structured output schema.

## Project files

```text
rift.py
    Main CLI and asynchronous enrichment pipeline.

config.py
    Runtime defaults and Config dataclass.

Icann_file_compatibility_cleaner.py
    ICANN-style zone-export compatibility converter.

tests/test_rift.py
    Standard-library regression tests.

requirements.txt
    Python runtime dependencies.

LICENSE.txt
    MIT license.
```

## Scope

Rift is not a general web crawler, search engine, browser automation framework, vulnerability scanner, or complete DNS zone parser. Its job is to turn large domain/URL lists into traceable lightweight web metadata.

## License

Rift is distributed under the MIT License.
