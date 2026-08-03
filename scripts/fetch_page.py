# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""Fetch raw wikitext for a Wikipedia page via the MediaWiki action API.

Usage: uv run scripts/fetch_page.py "<page title>"
Prints the wikitext to stdout. Also used as a library by the parser scripts.
"""
import sys
import time

import requests

HOST = "en.wikipedia.org"
API = f"https://{HOST}/w/api.php"
USER_AGENT = (
    "seniors-world-cup-comparison/0.1 "
    "(youth-to-senior squad overlap research; "
    "https://github.com/sbahamon/seniors-world-cup-comparison)"
)

# A full Phase 2 ingest is ~450 API calls (one parse and one expandtemplates per
# page, plus a pageprops batch per 50 players). Fired back to back that earns a
# sustained 429 and nine editions get recorded as `failed` for a reason that has
# nothing to do with the data. So: one request per second, and a BOUNDED backoff
# when the API says 429 anyway.
#
# This is not the retry loop CLAUDE.md rules out. That rule is about the egress
# proxy blocking a domain, where retrying cannot help and the answer is to ask
# for an allowlist entry. A 429 with a Retry-After header is the API telling us
# its rate and asking us to honour it. Four attempts, then it raises and the
# edition is recorded as failed like any other retrieval failure.
MIN_REQUEST_INTERVAL = 1.0  # seconds
MAX_RETRIES = 4

_session = requests.Session()
_last_request = 0.0


def api_get_host(host: str, params: dict, timeout: int = 30) -> requests.Response:
    """GET a MediaWiki API on `host`, throttled, with a bounded 429 backoff.

    `host` is a bare wiki hostname such as "es.wikipedia.org". The throttle is
    deliberately global rather than per-host: it exists to keep us inside
    Wikimedia's rate expectations, and every language wiki sits behind the same
    infrastructure, so spreading requests across hosts does not buy extra rate.
    """
    global _last_request
    url = f"https://{host}/w/api.php"
    for attempt in range(MAX_RETRIES + 1):
        pause = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request)
        if pause > 0:
            time.sleep(pause)
        resp = _session.get(
            url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout
        )
        _last_request = time.monotonic()
        if resp.status_code == 429 and attempt < MAX_RETRIES:
            header = resp.headers.get("Retry-After", "")
            delay = float(header) if header.isdigit() else 5.0 * 2**attempt
            print(f"    API returned 429; waiting {delay:.0f}s "
                  f"(attempt {attempt + 1} of {MAX_RETRIES})", flush=True)
            time.sleep(delay)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


def api_get(params: dict, timeout: int = 30) -> requests.Response:
    """GET the English Wikipedia API. Unchanged behaviour; see api_get_host."""
    return api_get_host(HOST, params, timeout)


def api_post_host(host: str, params: dict, timeout: int = 30) -> requests.Response:
    """POST a MediaWiki API query on `host`, throttled, with the same backoff.

    Needed for title batches on non-Latin wikis: fifty Cyrillic or Arabic
    titles percent-encode to well over the 8 KiB URL limit and the request
    comes back 414 rather than 200. The API accepts the identical parameters by
    POST for read queries, so this is a transport change and nothing else.
    """
    global _last_request
    url = f"https://{host}/w/api.php"
    for attempt in range(MAX_RETRIES + 1):
        pause = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request)
        if pause > 0:
            time.sleep(pause)
        resp = _session.post(
            url, data=params, headers={"User-Agent": USER_AGENT}, timeout=timeout
        )
        _last_request = time.monotonic()
        if resp.status_code == 429 and attempt < MAX_RETRIES:
            header = resp.headers.get("Retry-After", "")
            delay = float(header) if header.isdigit() else 5.0 * 2**attempt
            print(f"    API returned 429; waiting {delay:.0f}s "
                  f"(attempt {attempt + 1} of {MAX_RETRIES})", flush=True)
            time.sleep(delay)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


def fetch_wikitext(title: str, host: str = HOST) -> str:
    resp = api_get_host(host, {
        "action": "parse",
        "page": title,
        "prop": "wikitext",
        "format": "json",
        "formatversion": "2",
    })
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"MediaWiki API error for {title!r}: {data['error']}")
    return data["parse"]["wikitext"]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: uv run scripts/fetch_page.py '<page title>'")
    print(fetch_wikitext(sys.argv[1]))
