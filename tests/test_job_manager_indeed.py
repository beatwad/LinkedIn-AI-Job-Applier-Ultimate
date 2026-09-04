"""Tests for src/job_manager/indeed/job_manager_indeed.py (Indeed-specific methods)"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.job_manager.indeed.job_manager_indeed import IndeedJobManager
from src.pydantic_models.job_models import Job

INDEED_JOB_URL = "https://www.indeed.com/viewjob?jk=abc123"


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.url = INDEED_JOB_URL
    page.context = AsyncMock()
    return page


@pytest.fixture
def manager(mock_page):
    return IndeedJobManager(
        page=mock_page,
        linkedin_email="test@example.com",
        resume_anonymizer=MagicMock(),
        search_component=MagicMock(),
    )


@pytest.fixture
def test_job():
    return Job(
        job_title="Software Engineer",
        company_name="Tech Corp",
        url=INDEED_JOB_URL,
        job_description="We need a Python developer",
        apply_method="easy_apply",
    )


class TestGetVacanciesFromPage:
    @pytest.mark.asyncio
    async def test_returns_unique_cards(self, manager, mock_page):
        mock_card1 = AsyncMock()
        mock_card2 = AsyncMock()
        mock_title1 = AsyncMock()
        mock_title1.get_attribute = AsyncMock(return_value="abc1")
        mock_title2 = AsyncMock()
        mock_title2.get_attribute = AsyncMock(return_value="abc2")

        with (
            patch.object(mock_page, "wait_for_selector", new_callable=AsyncMock),
            patch.object(manager, "_scroll_left_panel", new_callable=AsyncMock),
            patch(
                "src.job_manager.indeed.job_manager_indeed.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_card1, mock_card2],
            ),
            patch(
                "src.job_manager.indeed.job_manager_indeed.find_element_safely",
                new_callable=AsyncMock,
                side_effect=[mock_title1, mock_title2],
            ),
            patch("src.job_manager.indeed.job_manager_indeed.emit_event"),
        ):
            result = await manager.get_vacancies_from_page()

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_deduplicates_same_jk(self, manager, mock_page):
        mock_card1 = AsyncMock()
        mock_card2 = AsyncMock()
        mock_title1 = AsyncMock()
        mock_title1.get_attribute = AsyncMock(return_value="same_jk")
        mock_title2 = AsyncMock()
        mock_title2.get_attribute = AsyncMock(return_value="same_jk")

        with (
            patch.object(mock_page, "wait_for_selector", new_callable=AsyncMock),
            patch.object(manager, "_scroll_left_panel", new_callable=AsyncMock),
            patch(
                "src.job_manager.indeed.job_manager_indeed.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_card1, mock_card2],
            ),
            patch(
                "src.job_manager.indeed.job_manager_indeed.find_element_safely",
                new_callable=AsyncMock,
                side_effect=[mock_title1, mock_title2],
            ),
            patch("src.job_manager.indeed.job_manager_indeed.emit_event"),
        ):
            result = await manager.get_vacancies_from_page()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_cards(self, manager, mock_page):
        with (
            patch.object(mock_page, "wait_for_selector", new_callable=AsyncMock),
            patch.object(manager, "_scroll_left_panel", new_callable=AsyncMock),
            patch(
                "src.job_manager.indeed.job_manager_indeed.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await manager.get_vacancies_from_page()

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_exception(self, manager, mock_page):
        with (
            patch.object(
                mock_page,
                "wait_for_selector",
                new_callable=AsyncMock,
                side_effect=Exception("timeout"),
            ),
            patch("src.job_manager.indeed.job_manager_indeed.debug_capture"),
        ):
            result = await manager.get_vacancies_from_page()

        assert result == []

    @pytest.mark.asyncio
    async def test_includes_card_with_no_title_element(self, manager, mock_page):
        mock_card = AsyncMock()

        with (
            patch.object(mock_page, "wait_for_selector", new_callable=AsyncMock),
            patch.object(manager, "_scroll_left_panel", new_callable=AsyncMock),
            patch(
                "src.job_manager.indeed.job_manager_indeed.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_card],
            ),
            patch(
                "src.job_manager.indeed.job_manager_indeed.find_element_safely",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("src.job_manager.indeed.job_manager_indeed.emit_event"),
        ):
            result = await manager.get_vacancies_from_page()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_increments_total_discovered_jobs(self, manager, mock_page):
        manager.total_discovered_jobs = 5
        mock_card = AsyncMock()
        mock_title = AsyncMock()
        mock_title.get_attribute = AsyncMock(return_value="unique_jk")

        with (
            patch.object(mock_page, "wait_for_selector", new_callable=AsyncMock),
            patch.object(manager, "_scroll_left_panel", new_callable=AsyncMock),
            patch(
                "src.job_manager.indeed.job_manager_indeed.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_card],
            ),
            patch(
                "src.job_manager.indeed.job_manager_indeed.find_element_safely",
                new_callable=AsyncMock,
                return_value=mock_title,
            ),
            patch("src.job_manager.indeed.job_manager_indeed.emit_event"),
        ):
            await manager.get_vacancies_from_page()

        assert manager.total_discovered_jobs == 6


class TestExtractJobFromCard:
    @pytest.mark.asyncio
    async def test_returns_job_with_easy_apply(self, manager):
        card = AsyncMock()
        title_el = AsyncMock()
        title_el.text_content = AsyncMock(return_value="Software Engineer")
        title_el.get_attribute = AsyncMock(
            side_effect=lambda attr: "abc1" if attr == "data-jk" else None
        )
        company_el = AsyncMock()
        company_el.text_content = AsyncMock(return_value="Tech Corp")
        location_el = AsyncMock()
        location_el.text_content = AsyncMock(return_value="New York")
        easy_apply_badge = AsyncMock()

        def find_element_side_effect(el, selector, timeout=None):
            from src.job_manager.indeed.job_manager_indeed import (
                INDEED_COMPANY_SELECTOR,
                INDEED_EASY_APPLY_BADGE,
                INDEED_JOB_TITLE_SELECTOR,
                INDEED_LOCATION_SELECTOR,
            )

            if selector == INDEED_JOB_TITLE_SELECTOR:
                return title_el
            elif selector == INDEED_COMPANY_SELECTOR:
                return company_el
            elif selector == INDEED_LOCATION_SELECTOR:
                return location_el
            elif selector == INDEED_EASY_APPLY_BADGE:
                return easy_apply_badge
            return None

        with patch(
            "src.job_manager.indeed.job_manager_indeed.find_element_safely",
            new_callable=AsyncMock,
            side_effect=find_element_side_effect,
        ):
            job = await manager._extract_job_from_card(card)

        assert job is not None
        assert job.job_title == "software engineer"
        assert job.company_name == "tech corp"
        assert job.location == "new york"
        assert job.apply_method == "easy_apply"
        assert job.url == "https://www.indeed.com/viewjob?jk=abc1"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_title_element(self, manager):
        card = AsyncMock()
        with patch(
            "src.job_manager.indeed.job_manager_indeed.find_element_safely",
            new_callable=AsyncMock,
            return_value=None,
        ):
            job = await manager._extract_job_from_card(card)

        assert job is None

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, manager):
        card = AsyncMock()
        with (
            patch(
                "src.job_manager.indeed.job_manager_indeed.find_element_safely",
                new_callable=AsyncMock,
                side_effect=Exception("DOM error"),
            ),
            patch("src.job_manager.indeed.job_manager_indeed.debug_capture"),
        ):
            job = await manager._extract_job_from_card(card)

        assert job is None

    @pytest.mark.asyncio
    async def test_builds_url_from_href_when_no_jk(self, manager):
        card = AsyncMock()
        title_el = AsyncMock()
        title_el.text_content = AsyncMock(return_value="Engineer")
        title_el.get_attribute = AsyncMock(
            side_effect=lambda attr: None if attr == "data-jk" else "/viewjob?jk=xyz"
        )
        company_el = AsyncMock()
        company_el.text_content = AsyncMock(return_value="Corp")
        location_el = AsyncMock()
        location_el.text_content = AsyncMock(return_value="Remote")
        easy_apply_badge = AsyncMock()

        def find_element_side_effect(el, selector, timeout=None):
            from src.job_manager.indeed.job_manager_indeed import (
                INDEED_COMPANY_SELECTOR,
                INDEED_EASY_APPLY_BADGE,
                INDEED_JOB_TITLE_SELECTOR,
                INDEED_LOCATION_SELECTOR,
            )

            if selector == INDEED_JOB_TITLE_SELECTOR:
                return title_el
            elif selector == INDEED_COMPANY_SELECTOR:
                return company_el
            elif selector == INDEED_LOCATION_SELECTOR:
                return location_el
            elif selector == INDEED_EASY_APPLY_BADGE:
                return easy_apply_badge
            return None

        with patch(
            "src.job_manager.indeed.job_manager_indeed.find_element_safely",
            new_callable=AsyncMock,
            side_effect=find_element_side_effect,
        ):
            job = await manager._extract_job_from_card(card)

        assert job is not None
        assert "indeed.com" in job.url


class TestExtractJobDescriptionFromPage:
    @pytest.mark.asyncio
    async def test_returns_description_text(self, manager):
        mock_page = AsyncMock()
        mock_el = AsyncMock()
        mock_el.text_content = AsyncMock(return_value="  We are hiring a Python developer.  ")

        with patch(
            "src.job_manager.indeed.job_manager_indeed.find_element_safely",
            new_callable=AsyncMock,
            return_value=mock_el,
        ):
            result = await manager._extract_job_description_from_page(mock_page)

        assert result == "We are hiring a Python developer."

    @pytest.mark.asyncio
    async def test_returns_empty_string_when_no_element(self, manager):
        mock_page = AsyncMock()
        with patch(
            "src.job_manager.indeed.job_manager_indeed.find_element_safely",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await manager._extract_job_description_from_page(mock_page)

        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_string_on_exception(self, manager):
        mock_page = AsyncMock()
        with patch(
            "src.job_manager.indeed.job_manager_indeed.find_element_safely",
            new_callable=AsyncMock,
            side_effect=Exception("network error"),
        ):
            result = await manager._extract_job_description_from_page(mock_page)

        assert result == ""


class TestExtractCompanyDescription:
    @pytest.mark.asyncio
    async def test_returns_company_description(self, manager):
        mock_page = AsyncMock()
        mock_el = AsyncMock()
        mock_el.text_content = AsyncMock(
            return_value="  We are a leading technology company building great products.  "
        )

        with patch(
            "src.job_manager.indeed.job_manager_indeed.find_element_safely",
            new_callable=AsyncMock,
            return_value=mock_el,
        ):
            result = await manager._extract_company_description(mock_page)

        assert result == "We are a leading technology company building great products."

    @pytest.mark.asyncio
    async def test_returns_empty_for_short_text(self, manager):
        mock_page = AsyncMock()
        mock_el = AsyncMock()
        mock_el.text_content = AsyncMock(return_value="Short")

        with patch(
            "src.job_manager.indeed.job_manager_indeed.find_element_safely",
            new_callable=AsyncMock,
            return_value=mock_el,
        ):
            result = await manager._extract_company_description(mock_page)

        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_element(self, manager):
        mock_page = AsyncMock()
        with patch(
            "src.job_manager.indeed.job_manager_indeed.find_element_safely",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await manager._extract_company_description(mock_page)

        assert result == ""


class TestGoToNextPage:
    @pytest.mark.asyncio
    async def test_returns_true_and_increments_page(self, manager, mock_page):
        manager.page_num = 0
        mock_btn = AsyncMock()

        with (
            patch(
                "src.job_manager.indeed.job_manager_indeed.find_element_safely",
                new_callable=AsyncMock,
                return_value=mock_btn,
            ),
            patch.object(manager, "_dismiss_overlays", new_callable=AsyncMock),
            patch.object(
                manager,
                "_current_page_signature",
                new_callable=AsyncMock,
                side_effect=["page-1", "page-2"],
            ),
            patch(
                "src.job_manager.indeed.job_manager_indeed.safe_click",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(mock_page, "wait_for_load_state", new_callable=AsyncMock),
            patch("src.job_manager.indeed.job_manager_indeed.async_pause"),
            patch("src.job_manager.indeed.job_manager_indeed.emit_event"),
        ):
            result = await manager._go_to_next_page()

        assert result is True
        assert manager.page_num == 1

    @pytest.mark.asyncio
    async def test_returns_false_when_no_next_button(self, manager, mock_page):
        with patch(
            "src.job_manager.indeed.job_manager_indeed.find_element_safely",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await manager._go_to_next_page()

        assert result is False
        assert manager.page_num == 0

    @pytest.mark.asyncio
    async def test_falls_back_to_force_click(self, manager, mock_page):
        manager.page_num = 0
        mock_btn = AsyncMock()
        mock_btn.click = AsyncMock()

        with (
            patch(
                "src.job_manager.indeed.job_manager_indeed.find_element_safely",
                new_callable=AsyncMock,
                return_value=mock_btn,
            ),
            patch.object(manager, "_dismiss_overlays", new_callable=AsyncMock),
            patch.object(
                manager,
                "_current_page_signature",
                new_callable=AsyncMock,
                side_effect=["page-1", "page-2"],
            ),
            patch(
                "src.job_manager.indeed.job_manager_indeed.safe_click",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch.object(mock_page, "wait_for_load_state", new_callable=AsyncMock),
            patch("src.job_manager.indeed.job_manager_indeed.async_pause"),
            patch("src.job_manager.indeed.job_manager_indeed.emit_event"),
        ):
            result = await manager._go_to_next_page()

        assert result is True
        mock_btn.click.assert_called_once_with(force=True, timeout=5000)

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, manager, mock_page):
        with (
            patch(
                "src.job_manager.indeed.job_manager_indeed.find_element_safely",
                new_callable=AsyncMock,
                side_effect=Exception("network error"),
            ),
            patch("src.job_manager.indeed.job_manager_indeed.debug_capture"),
        ):
            result = await manager._go_to_next_page()

        assert result is False


class TestEasyApply:
    @pytest.mark.asyncio
    async def test_delegates_to_indeed_easy_applier(self, manager, test_job):
        mock_applier = AsyncMock()
        mock_applier.apply_to_job = AsyncMock(return_value=(("Success", ""), None))
        mock_page = AsyncMock()

        with patch(
            "src.job_manager.indeed.job_manager_indeed.IndeedEasyApplier",
            return_value=mock_applier,
        ):
            result = await manager.easy_apply(test_job, mock_page)

        assert result == ("Success", "")
        mock_applier.apply_to_job.assert_called_once_with(test_job)


class TestApplyJob:
    def _setup_manager(self, manager):
        manager.success_applies_num = 0
        manager.max_applies_num = 10
        manager.applies_num = 0
        manager.error_num = 0
        manager.success_companies = {}
        manager.skipped_companies = {}
        manager.failed_companies = {}
        manager.apply_once_at_company = True
        manager.pause_checker = None
        manager.search_component = MagicMock()
        manager.search_component.is_job_blacklisted.return_value = False

    @pytest.mark.asyncio
    async def test_skips_when_card_extraction_returns_none(self, manager):
        self._setup_manager(manager)
        with patch.object(
            manager, "_extract_job_from_card", new_callable=AsyncMock, return_value=None
        ):
            result = await manager.apply_job(AsyncMock())

        assert result == "Skip"

    @pytest.mark.asyncio
    async def test_skips_blacklisted_job(self, manager, mock_page, test_job):
        self._setup_manager(manager)
        manager.search_component.is_job_blacklisted.return_value = True

        with (
            patch.object(
                manager, "_extract_job_from_card", new_callable=AsyncMock, return_value=test_job
            ),
            patch.object(manager, "_handle_apply_result", new_callable=AsyncMock),
        ):
            result = await manager.apply_job(AsyncMock())

        assert result == "Skip"

    @pytest.mark.asyncio
    async def test_skips_already_seen_job(self, manager, mock_page, test_job):
        self._setup_manager(manager)
        manager.success_companies = {
            "Tech Corp": [{"job_title": "Software Engineer", "url": INDEED_JOB_URL}]
        }

        with (
            patch.object(
                manager, "_extract_job_from_card", new_callable=AsyncMock, return_value=test_job
            ),
            patch.object(manager, "_handle_apply_result", new_callable=AsyncMock),
            patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False),
        ):
            result = await manager.apply_job(AsyncMock())

        assert result == "Skip"

    @pytest.mark.asyncio
    async def test_skips_external_apply_in_easy_apply_only_mode(self, manager, mock_page):
        self._setup_manager(manager)
        external_job = Job(
            job_title="Engineer",
            company_name="Corp",
            url=INDEED_JOB_URL,
            apply_method="external",
        )

        with (
            patch.object(
                manager,
                "_extract_job_from_card",
                new_callable=AsyncMock,
                return_value=external_job,
            ),
            patch.object(manager, "_handle_apply_result", new_callable=AsyncMock),
            patch("src.job_manager.indeed.job_manager_indeed.EASY_APPLY_ONLY_MODE", True),
            patch("src.job_manager.indeed.job_manager_indeed.COLLECT_INFO_MODE", False),
        ):
            result = await manager.apply_job(AsyncMock())

        assert result == "Skip"

    @pytest.mark.asyncio
    async def test_returns_limit_when_max_applies_reached(self, manager, mock_page, test_job):
        self._setup_manager(manager)
        manager.success_applies_num = 10
        manager.max_applies_num = 10
        new_page = AsyncMock()
        mock_page.context.new_page = AsyncMock(return_value=new_page)

        mock_llm = MagicMock()
        mock_llm.job_is_interesting.return_value = (True, 80, "Great fit")
        mock_llm.set_job = MagicMock()
        manager.llm_answerer_component = mock_llm

        with (
            patch.object(
                manager, "_extract_job_from_card", new_callable=AsyncMock, return_value=test_job
            ),
            patch.object(
                manager,
                "_extract_job_description_from_page",
                new_callable=AsyncMock,
                return_value="desc",
            ),
            patch.object(
                manager,
                "_extract_company_description",
                new_callable=AsyncMock,
                return_value="about",
            ),
            patch.object(
                manager, "easy_apply", new_callable=AsyncMock, return_value=("Success", "")
            ),
            patch.object(manager, "_handle_apply_result", new_callable=AsyncMock),
            patch.object(manager, "_extract_skills_from_vacancy", return_value="Python"),
            patch.object(manager, "_update_skill_stat"),
            patch("src.job_manager.indeed.job_manager_indeed.async_pause"),
            patch("src.job_manager.indeed.job_manager_indeed.COLLECT_INFO_MODE", False),
            patch("src.job_manager.indeed.job_manager_indeed.MONKEY_MODE", False),
            patch("src.job_manager.indeed.job_manager_indeed.EASY_APPLY_ONLY_MODE", True),
        ):
            result = await manager.apply_job(AsyncMock())

        assert result == "Limit"

    @pytest.mark.asyncio
    async def test_returns_ok_in_collect_info_mode(self, manager, mock_page, test_job):
        self._setup_manager(manager)
        new_page = AsyncMock()
        mock_page.context.new_page = AsyncMock(return_value=new_page)

        mock_llm = MagicMock()
        mock_llm.job_is_interesting.return_value = (True, 80, "Great fit")
        mock_llm.set_job = MagicMock()
        manager.llm_answerer_component = mock_llm

        with (
            patch.object(
                manager, "_extract_job_from_card", new_callable=AsyncMock, return_value=test_job
            ),
            patch.object(
                manager,
                "_extract_job_description_from_page",
                new_callable=AsyncMock,
                return_value="desc",
            ),
            patch.object(
                manager,
                "_extract_company_description",
                new_callable=AsyncMock,
                return_value="about",
            ),
            patch.object(manager, "_extract_skills_from_vacancy", return_value="Python"),
            patch.object(manager, "_update_skill_stat"),
            patch.object(manager, "_save_interesting_job"),
            patch("src.job_manager.indeed.job_manager_indeed.async_pause"),
            patch("src.job_manager.indeed.job_manager_indeed.COLLECT_INFO_MODE", True),
            patch("src.job_manager.indeed.job_manager_indeed.MONKEY_MODE", False),
        ):
            result = await manager.apply_job(AsyncMock())

        assert result == "Ok"

    @pytest.mark.asyncio
    async def test_skips_uninteresting_job(self, manager, mock_page, test_job):
        self._setup_manager(manager)
        new_page = AsyncMock()
        mock_page.context.new_page = AsyncMock(return_value=new_page)

        mock_llm = MagicMock()
        mock_llm.job_is_interesting.return_value = (False, 0, "Not relevant")
        manager.llm_answerer_component = mock_llm

        with (
            patch.object(
                manager, "_extract_job_from_card", new_callable=AsyncMock, return_value=test_job
            ),
            patch.object(
                manager,
                "_extract_job_description_from_page",
                new_callable=AsyncMock,
                return_value="desc",
            ),
            patch.object(
                manager,
                "_extract_company_description",
                new_callable=AsyncMock,
                return_value="about",
            ),
            patch.object(manager, "_handle_apply_result", new_callable=AsyncMock),
            patch("src.job_manager.indeed.job_manager_indeed.async_pause"),
            patch("src.job_manager.indeed.job_manager_indeed.COLLECT_INFO_MODE", False),
            patch("src.job_manager.indeed.job_manager_indeed.MONKEY_MODE", False),
        ):
            result = await manager.apply_job(AsyncMock())

        assert result == "Skip"
