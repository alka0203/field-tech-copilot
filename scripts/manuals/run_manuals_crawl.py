"""Runs every brand spider in sequence and reports total manifest rows.

Usage: python scripts/manuals/run_manuals_crawl.py
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

SPIDERS = ["spider_carrier.py", "spider_mitsubishi.py", "spider_daikin.py"]


def main() -> None:
    here = Path(__file__).parent
    failed = []
    for spider in SPIDERS:
        print(f"\n=== Running {spider} ===")
        try:
            runpy.run_path(str(here / spider), run_name="__main__")
        except SystemExit as e:
            if e.code:
                failed.append(spider)
        except Exception as e:
            print(f"[fail] {spider} raised: {e}", file=sys.stderr)
            failed.append(spider)
    if failed:
        print(f"\nSpiders with failures: {failed}", file=sys.stderr)
        sys.exit(1)
    print("\nAll manual spiders completed without errors.")


if __name__ == "__main__":
    main()
