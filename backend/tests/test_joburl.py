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
            # A bare anchor names a section of a page, not a posting.
            ("https://amazon.jobs/1234#apply", "https://amazon.jobs/1234"),
            ("https://amazon.jobs/1234#top", "https://amazon.jobs/1234"),
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


class TestTwoOpeningsAtOneCompany:
    """The reported bug: one company's whole board collapsing into one row.

    Every parameter below was on the tracking list and therefore stripped, so
    two genuinely different openings normalised to the bare domain and each got
    a red duplicate flag. A company hiring for six roles is ordinary; being told
    you already applied to five of them is not.
    """

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            # `position` is a job id on plenty of boards, not a page number.
            (
                "https://careers.acme.com/?position=111",
                "https://careers.acme.com/?position=222",
            ),
            (
                "https://acme.com/careers?refId=abc",
                "https://acme.com/careers?refId=xyz",
            ),
            (
                "https://acme.com/careers?pageNum=2",
                "https://acme.com/careers?pageNum=9",
            ),
            (
                "https://acme.com/j?source=111",
                "https://acme.com/j?source=222",
            ),
            ("https://acme.com/j?src=111", "https://acme.com/j?src=222"),
            ("https://acme.com/j?ref=111", "https://acme.com/j?ref=222"),
            ("https://acme.com/j?trk=111", "https://acme.com/j?trk=222"),
            ("https://acme.com/j?eBP=111", "https://acme.com/j?eBP=222"),
            # A careers site that routes on the hash keeps the whole posting
            # there. Dropping the fragment left only the domain.
            (
                "https://careers.acme.com/#/jobs/111",
                "https://careers.acme.com/#/jobs/222",
            ),
            (
                "https://acme.com/careers#jobId=55",
                "https://acme.com/careers#jobId=66",
            ),
        ],
    )
    def test_two_openings_are_not_one(self, a: str, b: str) -> None:
        assert normalise_job_url(a) != normalise_job_url(b)

    def test_a_whole_board_stays_separate(self) -> None:
        rows = [
            (str(i), f"https://careers.acme.com/?position={i}") for i in range(6)
        ]
        assert duplicate_groups(rows) == {}

    def test_but_the_same_opening_twice_is_still_caught(self) -> None:
        rows = [
            ("a", "https://careers.acme.com/?position=111"),
            ("b", "careers.acme.com?position=111"),
            ("c", "https://careers.acme.com/?position=222"),
        ]
        assert duplicate_groups(rows) == {"a": ["b"], "b": ["a"]}


class TestCampaignTagsStillCollapse:
    """The one thing that is still stripped, and why it is safe.

    A campaign tag is added by an ad platform or a share link. No board has ever
    used `utm_source` as a job id, so removing it cannot invent a duplicate — it
    can only catch the same posting arriving from two places.
    """

    @pytest.mark.parametrize(
        "tag",
        [
            "utm_source=linkedin",
            "utm_medium=cpc",
            "utm_campaign=spring",
            "gclid=xyz",
            "fbclid=abc",
            "msclkid=def",
            "mc_cid=1&mc_eid=2",
        ],
    )
    def test_a_tagged_link_matches_the_plain_one(self, tag: str) -> None:
        assert normalise_job_url(f"https://acme.com/j/9?{tag}") == normalise_job_url(
            "https://acme.com/j/9"
        )

    def test_a_tag_does_not_erase_the_job_id_beside_it(self) -> None:
        assert normalise_job_url(
            "https://acme.com/j?position=7&utm_source=linkedin"
        ) == normalise_job_url("https://acme.com/j?position=7")
        assert normalise_job_url(
            "https://acme.com/j?position=7&utm_source=linkedin"
        ) != normalise_job_url("https://acme.com/j?position=8")


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
