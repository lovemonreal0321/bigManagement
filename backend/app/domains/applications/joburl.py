"""Recognising when two rows point at the same job posting.

Comparing the raw strings is useless: the same posting arrives as
`amazon.jobs/1234`, `https://www.amazon.jobs/1234/`, and
`https://amazon.jobs/1234?utm_source=linkedin`. A duplicate flag that misses
those is not worth showing.

The whole link is compared — path, query and fragment. Only a campaign tag can
be dropped, because those are the one thing that provably never identifies a
posting; everything else is somebody's job id somewhere. `?position=`,
`?refId=`, `?pageNum=` and the `#/jobs/1234` of a hash-routed careers site all
distinguish two openings at the same company, and treating any of them as noise
collapsed a company's entire board into one row.

The asymmetry is deliberate. A missed duplicate shows two rows that a person
can see are the same. A false duplicate says "you already applied here" about a
job they have not applied to, and that one costs an application.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit, urlunsplit

#: Campaign and click tracking, and nothing else. Every parameter here is added
#: by an ad platform or a share link; none is ever a posting's identity. Any
#: parameter not on this list is kept, because on real boards the job id lives
#: in one of them (`?jobId=`, `?gh_jid=`, `?position=`, `?refId=`).
TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_name",
        "gclid",
        "gbraid",
        "wbraid",
        "dclid",
        "fbclid",
        "msclkid",
        "twclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "_hsenc",
        "_hsmi",
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
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in TRACKING_PARAMS
    ]
    # Sorted so parameter order does not create a false difference.
    query = "&".join(f"{k}={v}" for k, v in sorted(kept))

    # A fragment is kept only when it carries structure — `#/jobs/1234` is
    # where a hash-routed careers site keeps the posting, and dropping it made
    # every job on that site look like the same one. A bare `#apply` names a
    # section of one page and is discarded.
    fragment = parts.fragment.rstrip("/")
    if not any(char in fragment for char in "/=&"):
        fragment = ""

    # The scheme never distinguishes one posting from another.
    return urlunsplit(("", host, path, query, fragment)).lstrip("/") or host


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
