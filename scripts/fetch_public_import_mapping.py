#!/usr/bin/env python3

"""Fetch the fixed public mapping snapshot used by the V2 resolver.

This is an explicit preparation step, not a network request made during a
repair evaluation.  The resulting files are kept with the experiment inputs
and their hashes are recorded by ``evaluation_manifest.py``.
"""

import argparse
import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PIPREQS_COMMIT = "48dbafd39003b9de177b8d314795e45797555850"
PIPREQS_MAPPING_URL = (
    "https://raw.githubusercontent.com/bndr/pipreqs/"
    f"{PIPREQS_COMMIT}/pipreqs/mapping"
)
PIPREQS_LICENSE_URL = (
    "https://raw.githubusercontent.com/bndr/pipreqs/"
    f"{PIPREQS_COMMIT}/LICENSE"
)


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ma-thesis-v2-mapping-fetch/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the attributed pipreqs import mapping snapshot.")
    parser.add_argument("--output-dir", default="data/public-import-mapping")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping = fetch_bytes(PIPREQS_MAPPING_URL)
    license_text = fetch_bytes(PIPREQS_LICENSE_URL)
    mapping_path = output_dir / "pipreqs-mapping.txt"
    license_path = output_dir / "pipreqs-LICENSE.txt"
    metadata_path = output_dir / "pipreqs-mapping-provenance.json"
    mapping_path.write_bytes(mapping)
    license_path.write_bytes(license_text)
    metadata_path.write_text(json.dumps({
        "source_project": "bndr/pipreqs",
        "source_url": PIPREQS_MAPPING_URL,
        "source_commit": PIPREQS_COMMIT,
        "license_url": PIPREQS_LICENSE_URL,
        "license": "Apache-2.0",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "mapping_sha256": hashlib.sha256(mapping).hexdigest(),
        "license_sha256": hashlib.sha256(license_text).hexdigest(),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
