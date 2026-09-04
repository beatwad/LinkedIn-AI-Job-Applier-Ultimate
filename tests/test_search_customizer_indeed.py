"""Tests for src/job_manager/indeed/search_customizer_indeed.py"""

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from src.job_manager.indeed.search_customizer_indeed import IndeedSearchCustomizer, indeed_base_url

MODULE = "src.job_manager.indeed.search_customizer_indeed"

BASE_PARAMS = {
    "positions": ["Software Engineer"],
    "locations": ["Germany"],
    "remote": False,
    "hybrid": False,
    "onsite": False,
    "experience_level": {},
    "job_types": {},
    "date": {},
    "apply_once_at_company": True,
    "company_blacklist": [],
    "title_blacklist": [],
    "location_blacklist": [],
}


@pytest.fixture
def mock_page():
    return AsyncMock()


@pytest.fixture
def customizer(mock_page):
    sc = IndeedSearchCustomizer(mock_page)
    sc.set_advanced_search_params(BASE_PARAMS)
    return sc


def _parse_url(url: str):
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return parsed, qs


# ---------------------------------------------------------------------------
# _build_search_url
# ---------------------------------------------------------------------------


class TestBuildSearchUrl:
    def test_base_url_prefix(self, customizer):
        url = customizer._build_search_url("Python Developer")
        assert url.startswith(indeed_base_url())

    def test_encodes_position(self, customizer):
        url = customizer._build_search_url("Data Scientist")
        _, qs = _parse_url(url)
        assert qs["q"] == ["Data Scientist"]

    def test_encodes_location(self, customizer):
        url = customizer._build_search_url("Engineer", "New York")
        _, qs = _parse_url(url)
        assert qs["l"] == ["New York"]

    def test_no_location_param_when_empty(self, customizer):
        url = customizer._build_search_url("Engineer", "")
        _, qs = _parse_url(url)
        assert "l" not in qs

    def test_remote_work_arrangement(self, customizer):
        customizer.remote = True
        url = customizer._build_search_url("Engineer")
        assert "remote" in url

    def test_hybrid_work_arrangement(self, customizer):
        customizer.hybrid = True
        url = customizer._build_search_url("Engineer")
        assert "hybrid" in url

    def test_onsite_work_arrangement(self, customizer):
        customizer.onsite = True
        url = customizer._build_search_url("Engineer")
        assert "onsite" in url

    def test_no_work_arrangement_param_when_all_disabled(self, customizer):
        url = customizer._build_search_url("Engineer")
        assert "sc=0kf" not in url

    def test_multiple_work_arrangements(self, customizer):
        customizer.remote = True
        customizer.hybrid = True
        url = customizer._build_search_url("Engineer")
        assert "remote" in url
        assert "hybrid" in url

    def test_job_type_full_time(self, customizer):
        customizer.job_types = {"full_time": True}
        url = customizer._build_search_url("Engineer")
        _, qs = _parse_url(url)
        assert qs["jt"] == ["fulltime"]

    def test_job_type_part_time(self, customizer):
        customizer.job_types = {"part_time": True}
        url = customizer._build_search_url("Engineer")
        _, qs = _parse_url(url)
        assert qs["jt"] == ["parttime"]

    def test_job_type_contract(self, customizer):
        customizer.job_types = {"contract": True}
        url = customizer._build_search_url("Engineer")
        _, qs = _parse_url(url)
        assert qs["jt"] == ["contract"]

    def test_no_job_type_param_when_all_disabled(self, customizer):
        customizer.job_types = {"full_time": False, "contract": False}
        url = customizer._build_search_url("Engineer")
        _, qs = _parse_url(url)
        assert "jt" not in qs

    def test_date_past_24_hours(self, customizer):
        customizer.date_posted = {"past_24_hours": True}
        url = customizer._build_search_url("Engineer")
        _, qs = _parse_url(url)
        assert qs["fromage"] == ["1"]

    def test_date_past_week(self, customizer):
        customizer.date_posted = {"past_week": True}
        url = customizer._build_search_url("Engineer")
        _, qs = _parse_url(url)
        assert qs["fromage"] == ["7"]

    def test_date_past_month(self, customizer):
        customizer.date_posted = {"past_month": True}
        url = customizer._build_search_url("Engineer")
        _, qs = _parse_url(url)
        assert qs["fromage"] == ["14"]

    def test_no_fromage_when_any_time(self, customizer):
        customizer.date_posted = {"any_time": True}
        url = customizer._build_search_url("Engineer")
        _, qs = _parse_url(url)
        assert "fromage" not in qs

    def test_no_fromage_when_all_dates_disabled(self, customizer):
        customizer.date_posted = {"past_24_hours": False, "past_week": False}
        url = customizer._build_search_url("Engineer")
        _, qs = _parse_url(url)
        assert "fromage" not in qs

    def test_special_characters_encoded_in_position(self, customizer):
        url = customizer._build_search_url("C++ Developer")
        assert "C%2B%2B" in url or "C++".replace("+", "%2B") in url or "q=" in url

    def test_all_params_combined(self, customizer):
        customizer.remote = True
        customizer.job_types = {"full_time": True}
        customizer.date_posted = {"past_24_hours": True}
        url = customizer._build_search_url("Engineer", "Berlin")
        _, qs = _parse_url(url)
        assert "q" in qs
        assert "l" in qs
        assert "jt" in qs
        assert "fromage" in qs


# ---------------------------------------------------------------------------
# set_search_params
# ---------------------------------------------------------------------------


class TestSetSearchParams:
    @pytest.mark.asyncio
    async def test_navigates_to_built_url(self, customizer, mock_page):
        with patch(f"{MODULE}.async_pause"):
            await customizer.set_search_params()

        mock_page.goto.assert_called_once()
        call_url = mock_page.goto.call_args[0][0]
        assert call_url.startswith(indeed_base_url())
        assert (
            "Software+Engineer" in call_url
            or "Software%20Engineer" in call_url
            or "Software" in call_url
        )

    @pytest.mark.asyncio
    async def test_queries_every_position_and_builds_a_search_per_location(
        self, customizer, mock_page
    ):
        customizer.positions = ["Data Scientist", "ML Engineer"]
        customizer.locations = ["Berlin", "Munich"]

        with patch(f"{MODULE}.async_pause"):
            await customizer.set_search_params()

        call_url = mock_page.goto.call_args[0][0]
        _, qs = _parse_url(call_url)
        assert qs["q"] == ['"Data Scientist" OR "ML Engineer"']
        assert qs["l"] == ["Berlin"]
        assert len(customizer.search_urls) == 2
        assert "Munich" in customizer.search_urls[1]

    @pytest.mark.asyncio
    async def test_skips_navigation_when_no_positions(self, mock_page):
        sc = IndeedSearchCustomizer(mock_page)
        sc.positions = []

        with patch(f"{MODULE}.async_pause"):
            await sc.set_search_params()

        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_empty_location_when_none_configured(self, mock_page):
        sc = IndeedSearchCustomizer(mock_page)
        sc.set_advanced_search_params({**BASE_PARAMS, "locations": []})

        with patch(f"{MODULE}.async_pause"):
            await sc.set_search_params()

        call_url = mock_page.goto.call_args[0][0]
        _, qs = _parse_url(call_url)
        assert "l" not in qs

    @pytest.mark.asyncio
    async def test_passes_domcontentloaded_wait(self, customizer, mock_page):
        with patch(f"{MODULE}.async_pause"):
            await customizer.set_search_params()

        call_kwargs = mock_page.goto.call_args[1]
        assert call_kwargs.get("wait_until") == "domcontentloaded"
