# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Fetch raw wikitext for a Wikipedia page via the MediaWiki action API.

Usage: uv run scripts/fetch_page.py "<page title>"
Prints the wikitext to stdout. Also used as a library by the parser scripts.
"""
import sys

import requests

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = (
    "seniors-world-cup-comparison/0.1 "
    "(youth-to-senior squad overlap research; "
    "https://github.com/sbahamon/seniors-world-cup-comparison)"
)


def fetch_wikitext(title: str) -> str:
    resp = requests.get(
        API,
        params={
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "format": "json",
            "formatversion": "2",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"MediaWiki API error for {title!r}: {data['error']}")
    return data["parse"]["wikitext"]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: uv run scripts/fetch_page.py '<page title>'")
    print(fetch_wikitext(sys.argv[1]))
