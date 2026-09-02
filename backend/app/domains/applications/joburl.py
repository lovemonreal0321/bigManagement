"""Recognising when two rows point at the same job posting.

Comparing the raw strings is useless: the same posting arrives as
`amazon.jobs/1234`, `https://www.amazon.jobs/1234/`, and
`https://amazon.jobs/1234?utm_source=linkedin&gh_src=abc`. A duplicate flag
that misses those is not worth showing.

Deliberately conservative: it strips things that provably do not identify a
posting, and leaves everything else alone. A false "duplicate" on two genuinely
different jobs would be worse than a missed one.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit, urlunsplit

#: Parameters that carry campaign or referral information rather than identity.
#: Anything not listed here is kept, because on many boards the job id lives in
#: the query string (`?jobId=`, `?gh_jid=`, `?lever-id=`).
TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "fbclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "ref",
        "referer",
        "referrer",
        "source",
        "src",
        "trk",
        "trkCampaign",
        "originalSubdomain",
        "refId",
        "eBP",
        "position",
        "pageNum",
    }
)


def normalise_job_url(raw: str | None) -> str | None:
    """A comparable form of a job posting URL, or `None` if there is nothing.

    Two URLs that normalise to the same string are treated as the same posting.
    """
    if not raw or not raw.strip():
        return None

    value = raw.strip()
    # A bare `amazon.jobs/1234` has no scheme; give it one so urlsplit finds the
    # host rather than reading the whole thing as a path.
    if "//" not in value.split("?", 1)[0][:8]:
        value = f"https://{value}"

    try:
        parts = urlsplit(value)
    except ValueError:
        return raw.strip().lower()

    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return raw.strip().lower()

    # Trailing slashes are cosmetic; a bare path is the site root.
    path = parts.path.rstrip("/") or ""

    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if key not in TRACKING_PARAMS
    ]
    # Sorted so parameter order does not create a false difference.
    query = "&".join(f"{k}={v}" for k, v in sorted(kept))

    # The scheme and fragment never distinguish one posting from another.
    return urlunsplit(("", host, path, query, "")).lstrip("/") or host


def duplicate_groups(rows: list[tuple[str, str | None]]) -> dict[str, list[str]]:
    """Map each row id to the *other* row ids sharing its posting.

    `rows` is `(row_id, job_url)`. Rows without a URL are never duplicates of
    anything — an empty link is missing information, not a match.
    """
    by_url: dict[str, list[str]] = {}
    for row_id, url in rows:
        key = normalise_job_url(url)
        if key is None:
            continue
        by_url.setdefault(key, []).append(row_id)

    duplicates: dict[str, list[str]] = {}
    for ids in by_url.values():
        if len(ids) < 2:
            continue
        for row_id in ids:
            duplicates[row_id] = [other for other in ids if other != row_id]
    return duplicates
