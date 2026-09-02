"""Recognising the same job posting written several ways.

A false duplicate is worse than a missed one — it puts a red flag on a real,
separate application — so the tests below pin what must NOT match as hard as
what must.
"""

from __future__ import annotations

import pytest

from app.domains.applications.joburl import (
    duplicate_groups,
    normalise_job_url,
)


class TestTheSamePosting:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            # Scheme, host prefix and trailing slash are cosmetic.
            ("amazon.jobs/1234", "https://www.amazon.jobs/1234"),
            ("http://amazon.jobs/1234", "https://amazon.jobs/1234"),
            ("https://amazon.jobs/1234/", "https://amazon.jobs/1234"),
            ("https://AMAZON.jobs/1234", "https://amazon.jobs/1234"),
            # Campaign junk from a job board or a shared link.
            (
                "https://amazon.jobs/1234?utm_source=linkedin&utm_medium=cpc",
                "https://amazon.jobs/1234",
            ),
            ("https://amazon.jobs/1234?gclid=xyz", "https://amazon.jobs/1234"),
            # A fragment never identifies a posting.
            ("https://amazon.jobs/1234#apply", "https://amazon.jobs/1234"),
            # Parameter order is not meaningful.
            (
                "https://boards.co/j?team=ml&id=7",
                "https://boards.co/j?id=7&team=ml",
            ),
        ],
    )
    def test_these_are_the_same(self, a: str, b: str) -> None:
        assert normalise_job_url(a) == normalise_job_url(b)


class TestDifferentPostings:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("https://amazon.jobs/1234", "https://amazon.jobs/5678"),
            ("https://amazon.jobs/1234", "https://google.jobs/1234"),
            # The job id often lives in the query string, so a query that is
            # not tracking must survive.
            (
                "https://boards.greenhouse.io/acme?gh_jid=1",
                "https://boards.greenhouse.io/acme?gh_jid=2",
            ),
            ("https://jobs.lever.co/acme?lever-id=a", "https://jobs.lever.co/acme?lever-id=b"),
            # Different subdomains are different sites.
            ("https://uk.indeed.com/j/1", "https://us.indeed.com/j/1"),
        ],
    )
    def test_these_are_not(self, a: str, b: str) -> None:
        assert normalise_job_url(a) != normalise_job_url(b)


class TestNothingToCompare:
    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_is_none(self, value: str | None) -> None:
        assert normalise_job_url(value) is None

    def test_junk_still_returns_something_comparable(self) -> None:
        """Not a URL, but two rows holding the same junk are still the same."""
        assert normalise_job_url("see email") == normalise_job_url("SEE EMAIL")


class TestGrouping:
    def test_it_pairs_rows_sharing_a_posting(self) -> None:
        groups = duplicate_groups(
            [
                ("a", "https://amazon.jobs/1"),
                ("b", "amazon.jobs/1?utm_source=x"),
                ("c", "https://amazon.jobs/2"),
            ]
        )
        assert groups == {"a": ["b"], "b": ["a"]}

    def test_three_of_the_same_all_point_at_each_other(self) -> None:
        groups = duplicate_groups(
            [("a", "x.com/1"), ("b", "x.com/1"), ("c", "x.com/1")]
        )
        assert set(groups) == {"a", "b", "c"}
        assert sorted(groups["a"]) == ["b", "c"]

    def test_rows_without_a_link_are_never_duplicates(self) -> None:
        """An empty link is missing information, not a match."""
        assert duplicate_groups([("a", None), ("b", ""), ("c", "   ")]) == {}

    def test_a_lone_row_is_not_flagged(self) -> None:
        assert duplicate_groups([("a", "https://x.com/1")]) == {}
