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
    """Normalize one absolute DNS owner name from a zone export."""
    value = value.strip().rstrip(".").lower()
    if not value:
        return ""
    if value.startswith("_") or value.startswith("*."):
        return ""
    if "://" in value or "/" in value:
        return ""
    if not HOSTNAME_PATTERN.fullmatch(value):
        return ""
    return value


def _record_type(fields: list[str]) -> str:
    """Return the DNS record type from an ordinary ICANN/CZDS zone row."""
    lowered = [field.lower() for field in fields]
    try:
        class_index = lowered.index("in")
    except ValueError:
        return ""
    if class_index + 1 >= len(fields):
        return ""
    return lowered[class_index + 1]


def clean_zone_file(
    input_path: str | Path,
    output_path: str | Path,
) -> dict[str, int | str]:
    """Convert an ICANN/CZDS TLD zone export into Rift domain input.

    Only delegated-domain NS owners are emitted. Zone-apex records, DNSSEC
    material, glue A/AAAA records, and other owner names are intentionally
    excluded. ICANN/CZDS zone exports group records by owner, so duplicate NS
    rows can be removed as a streaming operation without retaining the zone in
    memory.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Output file must be different from the zone file.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    records_read = 0
    ns_records = 0
    delegated_domains = 0
    duplicate_ns_records = 0
    rejected = 0
    skipped_non_ns = 0
    apex = ""
    previous_emitted = ""

    with input_path.open(
        "r",
        encoding="utf-8-sig",
        errors="replace",
    ) as source, output_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as destination:
        for line in source:
            line = line.strip()
            if not line or line.startswith(";"):
                continue

            records_read += 1
            fields = line.split()
            if len(fields) < 4:
                rejected += 1
                continue

            owner = fields[0].strip().rstrip(".").lower()
            record_type = _record_type(fields)
            if not owner or not record_type:
                rejected += 1
                continue

            if record_type == "soa" and not apex:
                apex = owner
                continue

            if record_type != "ns":
                skipped_non_ns += 1
                continue

            ns_records += 1
            if apex and owner == apex:
                continue

            hostname = _clean_hostname(owner)
            if not hostname:
                rejected += 1
                continue

            if hostname == previous_emitted:
                duplicate_ns_records += 1
                continue

            destination.write(hostname + "\n")
            previous_emitted = hostname
            delegated_domains += 1

    return {
        "records_read": records_read,
        "ns_records": ns_records,
        "delegated_domains": delegated_domains,
        "duplicates": duplicate_ns_records,
        "rejected": rejected,
        "skipped_non_ns": skipped_non_ns,
        "output_count": delegated_domains,
        "zone_apex": apex,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Convert an ICANN/CZDS TLD zone export into a streaming, "
            "deduplicated domain list for Rift."
        )
    )
    parser.add_argument("input", help="Path to the ICANN/CZDS zone file")
    parser.add_argument("output", help="Path to the domain-list output file")
    args = parser.parse_args()

    stats = clean_zone_file(args.input, args.output)

    print(f"Records read:       {stats['records_read']:,}")
    print(f"NS records:         {stats['ns_records']:,}")
    print(f"Delegated domains:  {stats['delegated_domains']:,}")
    print(f"Duplicate NS rows:  {stats['duplicates']:,}")
    print(f"Skipped non-NS:     {stats['skipped_non_ns']:,}")
    print(f"Rejected rows:      {stats['rejected']:,}")
    print(f"Zone apex:          {stats['zone_apex'] or '(not detected)'}")
    print(f"Output file:        {args.output}")


if __name__ == "__main__":
    main()
