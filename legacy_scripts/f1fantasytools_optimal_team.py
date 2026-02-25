#!/usr/bin/env python3
"""Compute optimal F1 Fantasy team under a max budget using f1fantasytools.

This script is kept for backward compatibility; implementation lives in f1fantasy.data_sources.f1fantasytools.

Output JSON matches prior behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from f1fantasy.data_sources import f1fantasytools as ft


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=100.0, help="Maximum budget (e.g., 100)")
    ap.add_argument("--url", default=ft.URL)
    args = ap.parse_args()

    html = ft.fetch(args.url)
    payload = ft.extract_next_payload(html)
    data = ft.extract_json_object_from_payload(payload)

    out = ft.compute_optimal(args.budget, data)
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
