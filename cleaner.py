from __future__ import annotations

import argparse
import re
from pathlib import Path


HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)"
    r"(?:"
    r"[a-z0-9]"
    r"(?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"\."
    r")+"
    r"[a-z0-9]"
    r"(?:[a-z0-9-]{0,61}[a-z0-9])?$",
    re.IGNORECASE,
)


def _clean_hostname(value: str) -> str:
    """
    Normalize and validate a DNS hostname.

    Returns an empty string when the value is not a usable hostname.
    """
    value = value.strip()

    if not value:
        return ""

    # Remove the DNS root terminator.
    value = value.rstrip(".")

    if not value:
        return ""

    value = value.lower()

    # Ignore DNS service/meta names.
    if value.startswith("_"):
        return ""

    # Ignore wildcard records.
    if value.startswith("*."):
        return ""

    # Ignore values containing URL syntax.
    if "://" in value or "/" in value:
        return ""

    # Require a hostname with at least two labels.
    if not HOSTNAME_PATTERN.fullmatch(value):
        return ""

    return value


def clean_zone_file(
    input_path: str | Path,
    output_path: str | Path,
) -> dict[str, int]:
    """
    Read a DNS zone file and write a sorted, deduplicated URL list.

    The first whitespace-delimited field of each record is treated as
    the owner/hostname.

    Example input:

        example.com. 86400 IN NS ns1.example.com.
        example.com. 3600 IN A 192.0.2.1
        _dmarc.example.com. 60 IN TXT "..."
        other.org. 3600 IN NS ns1.other.org.

    Example output:

        https://example.com
        https://other.org
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.is_file():
        raise FileNotFoundError(
            f"Input file not found: {input_path}"
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    seen: set[str] = set()

    records_read = 0
    hostnames_found = 0
    duplicates = 0
    rejected = 0

    with input_path.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as source:

        for line in source:
            line = line.strip()

            if not line:
                continue

            # Ignore comment-only lines.
            if line.startswith(";"):
                continue

            records_read += 1

            fields = line.split()

            if not fields:
                rejected += 1
                continue

            hostname = _clean_hostname(fields[0])

            if not hostname:
                rejected += 1
                continue

            if hostname in seen:
                duplicates += 1
                continue

            seen.add(hostname)
            hostnames_found += 1

    hostnames = sorted(seen)

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as destination:

        for hostname in hostnames:
            destination.write(
                f"https://{hostname}\n"
            )

    return {
        "records_read": records_read,
        "hostnames_found": hostnames_found,
        "duplicates": duplicates,
        "rejected": rejected,
        "output_count": len(hostnames),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Clean a DNS zone file into a sorted, "
            "deduplicated URL list."
        )
    )

    parser.add_argument(
        "input",
        help="Path to the DNS zone file",
    )

    parser.add_argument(
        "output",
        help="Path to the cleaned URL output file",
    )

    args = parser.parse_args()

    stats = clean_zone_file(
        args.input,
        args.output,
    )

    print(f"Records read:    {stats['records_read']}")
    print(f"Hostnames found: {stats['hostnames_found']}")
    print(f"Duplicates:      {stats['duplicates']}")
    print(f"Rejected:        {stats['rejected']}")
    print(f"Output written:  {stats['output_count']}")
    print(f"Output file:     {args.output}")


if __name__ == "__main__":
    main()