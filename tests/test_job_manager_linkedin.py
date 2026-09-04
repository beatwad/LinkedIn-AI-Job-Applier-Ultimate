"""Tests for src/job_manager/linkedin/job_manager_linkedin.py (LinkedIn-specific methods)"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.job_manager.linkedin.job_manager_linkedin import LinkedInJobManager
from src.pydantic_models.job_models import Job

LINKEDIN_JOB_URL = "https://linkedin.com/jobs/view/123456"


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.url = LINKEDIN_JOB_URL
    page.context = AsyncMock()
    return page


@pytest.fixture
def manager(mock_page):
    return LinkedInJobManager(
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
        url=LINKEDIN_JOB_URL,
        job_description="We need a Python developer",
    )


class TestGetVacanciesFromPage:
    @pytest.mark.asyncio
    async def test_returns_vacancies_with_urls(self, manager):
        mock_element = AsyncMock()
        with (
            patch.object(manager, "_scroll_to_load_jobs"),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_element],
            ),
            patch.object(
                manager,
                "_extract_job_url",
                new_callable=AsyncMock,
                return_value=LINKEDIN_JOB_URL,
            ),
            patch("src.job_manager.linkedin.job_manager_linkedin.emit_event"),
        ):
            result = await manager.get_vacancies_from_page()

        assert len(result) == 1
        assert result[0]["url"] == LINKEDIN_JOB_URL
        assert result[0]["id"] == "123456"

    @pytest.mark.asyncio
    async def test_skips_element_with_no_url(self, manager):
        mock_element = AsyncMock()
        with (
            patch.object(manager, "_scroll_to_load_jobs"),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_element],
            ),
            patch.object(manager, "_extract_job_url", new_callable=AsyncMock, return_value=None),
            patch("src.job_manager.linkedin.job_manager_linkedin.emit_event"),
        ):
            result = await manager.get_vacancies_from_page()

        assert result == []

    @pytest.mark.asyncio
    async def test_skips_already_applied_job_card(self, manager):
        mock_element = MagicMock()
        applied_locator = MagicMock()
        applied_locator.count = AsyncMock(return_value=1)
        applied_item = MagicMock()
        applied_item.inner_text = AsyncMock(return_value="Applied")
        applied_locator.nth.return_value = applied_item
        mock_element.locator.return_value = applied_locator

        with (
            patch.object(manager, "_scroll_to_load_jobs"),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_element],
            ),
            patch.object(manager, "_extract_job_url", new_callable=AsyncMock) as mock_extract_url,
            patch("src.job_manager.linkedin.job_manager_linkedin.emit_event"),
        ):
            result = await manager.get_vacancies_from_page()

        assert result == []
        mock_extract_url.assert_not_called()

    @pytest.mark.asyncio
    async def test_detects_applied_job_card_from_text(self, manager):
        mock_element = MagicMock()
        mock_element.locator.side_effect = RuntimeError("locator unavailable")

        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.get_clean_text",
            new_callable=AsyncMock,
            return_value="Head of Digitalization\nMadison Pearl\nApplied",
        ):
            result = await manager._is_applied_job_card(mock_element)

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_exception(self, manager):
        with (
            patch.object(manager, "_scroll_to_load_jobs", side_effect=Exception("scroll error")),
            patch("src.job_manager.linkedin.job_manager_linkedin.debug_capture"),
        ):
            result = await manager.get_vacancies_from_page()

        assert result == []

    @pytest.mark.asyncio
    async def test_increments_total_discovered_jobs(self, manager):
        mock_element = AsyncMock()
        manager.total_discovered_jobs = 0
        with (
            patch.object(manager, "_scroll_to_load_jobs"),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_element, mock_element],
            ),
            patch.object(
                manager,
                "_extract_job_url",
                new_callable=AsyncMock,
                side_effect=[
                    "https://linkedin.com/jobs/view/123456",
                    "https://linkedin.com/jobs/view/123457",
                ],
            ),
            patch("src.job_manager.linkedin.job_manager_linkedin.emit_event"),
        ):
            await manager.get_vacancies_from_page()

        assert manager.total_discovered_jobs == 2


class TestExtractJobUrl:
    @pytest.mark.asyncio
    async def test_returns_url_with_https_prefix(self, manager):
        mock_element = AsyncMock()
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.get_element_attribute_safely",
            new_callable=AsyncMock,
            return_value="/jobs/view/999",
        ):
            result = await manager._extract_job_url(mock_element)

        assert result == "https://www.linkedin.com/jobs/view/999"

    @pytest.mark.asyncio
    async def test_returns_url_already_absolute(self, manager):
        mock_element = AsyncMock()
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.get_element_attribute_safely",
            new_callable=AsyncMock,
            return_value="https://linkedin.com/jobs/view/999",
        ):
            result = await manager._extract_job_url(mock_element)

        assert result == "https://linkedin.com/jobs/view/999"

    @pytest.mark.asyncio
    async def test_returns_canonical_url_from_recommended_current_job_id(self, manager):
        mock_element = AsyncMock()
        recommended_href = (
            "https://www.linkedin.com/jobs/collections/recommended?"
            "currentJobId=4401460753&start=0&trackingId=abc"
        )
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.get_element_attribute_safely",
            new_callable=AsyncMock,
            return_value=recommended_href,
        ):
            result = await manager._extract_job_url(mock_element)

        assert result == "https://www.linkedin.com/jobs/view/4401460753"

    @pytest.mark.asyncio
    async def test_returns_canonical_url_from_top_applicant_current_job_id(self, manager):
        mock_element = AsyncMock()
        top_applicant_href = (
            "https://www.linkedin.com/jobs/collections/top-applicant?"
            "currentJobId=4401460753&start=0&trackingId=abc"
        )
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.get_element_attribute_safely",
            new_callable=AsyncMock,
            return_value=top_applicant_href,
        ):
            result = await manager._extract_job_url(mock_element)

        assert result == "https://www.linkedin.com/jobs/view/4401460753"

    @pytest.mark.asyncio
    async def test_returns_canonical_url_from_data_job_id(self, manager):
        mock_element = AsyncMock()
        mock_element.get_attribute = AsyncMock(return_value="4401460753")
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.get_element_attribute_safely",
            new_callable=AsyncMock,
            return_value="",
        ):
            result = await manager._extract_job_url(mock_element)

        assert result == "https://www.linkedin.com/jobs/view/4401460753"

    @pytest.mark.asyncio
    async def test_rejects_non_linkedin_absolute_url(self, manager):
        mock_element = AsyncMock()
        mock_element.get_attribute = AsyncMock(return_value=None)
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.get_element_attribute_safely",
            new_callable=AsyncMock,
            return_value="https://malicious.com/jobs/view/999",
        ):
            result = await manager._extract_job_url(mock_element)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_href_found(self, manager):
        mock_element = AsyncMock()
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.get_element_attribute_safely",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await manager._extract_job_url(mock_element)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_href_has_no_jobs_view(self, manager):
        mock_element = AsyncMock()
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.get_element_attribute_safely",
            new_callable=AsyncMock,
            return_value="https://linkedin.com/company/techcorp",
        ):
            result = await manager._extract_job_url(mock_element)

        assert result is None


class TestGetDetailedJobDescription:
    @pytest.mark.asyncio
    async def test_extracts_job_id_from_url(self, manager, mock_page):
        mock_page.url = "https://linkedin.com/jobs/view/987654"
        manager.page = mock_page
        with (
            patch.object(manager, "_extract_job_title", new_callable=AsyncMock, return_value="Dev"),
            patch.object(
                manager, "_extract_company_name", new_callable=AsyncMock, return_value="Corp"
            ),
            patch.object(
                manager,
                "_extract_job_description",
                new_callable=AsyncMock,
                return_value="desc",
            ),
            patch.object(
                manager,
                "_extract_company_description",
                new_callable=AsyncMock,
                return_value="about",
            ),
        ):
            job = await manager._get_detailed_job_description()

        assert job.job_id == "987654"
        assert job.url == "https://linkedin.com/jobs/view/987654"

    @pytest.mark.asyncio
    async def test_returns_empty_job_on_extraction_error(self, manager, mock_page):
        mock_page.url = "https://linkedin.com/jobs/view/111"
        manager.page = mock_page
        with (
            patch.object(
                manager,
                "_extract_job_title",
                new_callable=AsyncMock,
                side_effect=Exception("network"),
            ),
            patch.object(
                manager,
                "_extract_company_name",
                new_callable=AsyncMock,
                side_effect=Exception("network"),
            ),
            patch.object(
                manager,
                "_extract_job_description",
                new_callable=AsyncMock,
                side_effect=Exception("network"),
            ),
            patch.object(
                manager,
                "_extract_company_description",
                new_callable=AsyncMock,
                side_effect=Exception("network"),
            ),
            patch("src.job_manager.linkedin.job_manager_linkedin.debug_capture"),
        ):
            job = await manager._get_detailed_job_description()

        assert isinstance(job, Job)

    @pytest.mark.asyncio
    async def test_url_not_set_when_not_jobs_view(self, manager, mock_page):
        mock_page.url = "https://linkedin.com/feed"
        manager.page = mock_page
        with (
            patch.object(manager, "_extract_job_title", new_callable=AsyncMock, return_value=""),
            patch.object(manager, "_extract_company_name", new_callable=AsyncMock, return_value=""),
            patch.object(
                manager,
                "_extract_job_description",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch.object(
                manager,
                "_extract_company_description",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            job = await manager._get_detailed_job_description()

        assert job.url == ""


class TestExtractJobTitle:
    @pytest.mark.asyncio
    async def test_returns_title_from_element(self, manager):
        mock_element = AsyncMock()
        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_element],
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.get_clean_text",
                new_callable=AsyncMock,
                return_value="Senior Engineer",
            ),
        ):
            result = await manager._extract_job_title()

        assert result == "Senior Engineer"

    @pytest.mark.asyncio
    async def test_extracts_title_from_comma_separated(self, manager):
        mock_element = AsyncMock()
        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_element],
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.get_clean_text",
                new_callable=AsyncMock,
                return_value="Senior Engineer, New York, USA",
            ),
        ):
            result = await manager._extract_job_title()

        assert result == "Senior Engineer"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_elements(self, manager):
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await manager._extract_job_title()

        assert result is None

    @pytest.mark.asyncio
    async def test_skips_short_title(self, manager):
        mock_element = AsyncMock()
        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_element],
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.get_clean_text",
                new_callable=AsyncMock,
                return_value="AI",
            ),
        ):
            result = await manager._extract_job_title()

        assert result is None


class TestExtractCompanyName:
    @pytest.mark.asyncio
    async def test_returns_company_name_from_link(self, manager):
        mock_element = AsyncMock()
        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_element],
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.get_clean_text",
                new_callable=AsyncMock,
                return_value="Acme Corp",
            ),
        ):
            result = await manager._extract_company_name()

        assert result == "Acme Corp"

    @pytest.mark.asyncio
    async def test_fallback_to_alert_paragraph(self, manager):
        mock_alert_element = AsyncMock()

        def find_elements_side_effect(page, selector, by):
            if "company" in selector:
                return []
            return [mock_alert_element]

        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                side_effect=find_elements_side_effect,
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.get_clean_text",
                new_callable=AsyncMock,
                return_value="Software Engineer, Acme Corp, CA, USA",
            ),
        ):
            result = await manager._extract_company_name()

        assert result == "Acme Corp"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_company_found(self, manager):
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await manager._extract_company_name()

        assert result is None


class TestExtractJobDescription:
    @pytest.mark.asyncio
    async def test_returns_description_from_element(self, manager):
        mock_element = AsyncMock()
        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_element_safely",
                new_callable=AsyncMock,
                return_value=mock_element,
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.get_clean_text",
                new_callable=AsyncMock,
                return_value="We are looking for a talented developer " * 5,
            ),
            patch.object(
                manager,
                "_extract_requirements_section",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await manager._extract_job_description()

        assert result is not None
        assert len(result) > 50

    @pytest.mark.asyncio
    async def test_appends_requirements_when_present(self, manager):
        mock_element = AsyncMock()
        long_desc = "We need a developer. " * 10
        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_element_safely",
                new_callable=AsyncMock,
                return_value=mock_element,
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.get_clean_text",
                new_callable=AsyncMock,
                return_value=long_desc,
            ),
            patch.object(
                manager,
                "_extract_requirements_section",
                new_callable=AsyncMock,
                return_value="• Python\n• Docker",
            ),
        ):
            result = await manager._extract_job_description()

        assert "• Python" in result
        assert long_desc.strip() in result

    @pytest.mark.asyncio
    async def test_returns_none_when_no_description(self, manager):
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.find_element_safely",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await manager._extract_job_description()

        assert result is None


class TestExtractRequirementsSection:
    @pytest.mark.asyncio
    async def test_returns_bullet_requirements(self, manager):
        mock_el1 = AsyncMock()
        mock_el2 = AsyncMock()

        texts = iter(["• Python 3+ years", "• Docker experience"])

        async def get_text(el):
            return next(texts)

        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_el1, mock_el2],
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.get_clean_text",
                side_effect=get_text,
            ),
        ):
            result = await manager._extract_requirements_section()

        assert result is not None
        assert "• Python 3+ years" in result
        assert "• Docker experience" in result

    @pytest.mark.asyncio
    async def test_stops_at_non_bullet_text(self, manager):
        mock_el1 = AsyncMock()
        mock_el2 = AsyncMock()

        texts = iter(["• Python 3+ years", "Some other section content"])

        async def get_text(el):
            return next(texts)

        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[mock_el1, mock_el2],
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.get_clean_text",
                side_effect=get_text,
            ),
        ):
            result = await manager._extract_requirements_section()

        assert result is not None
        assert "• Python 3+ years" in result
        assert "Some other section" not in result

    @pytest.mark.asyncio
    async def test_returns_none_when_no_elements(self, manager):
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await manager._extract_requirements_section()

        assert result is None


class TestExtractCompanyDescription:
    @pytest.mark.asyncio
    async def test_returns_company_description(self, manager):
        mock_element = AsyncMock()
        long_text = "We are a leading technology company. " * 5
        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_element_safely",
                new_callable=AsyncMock,
                return_value=mock_element,
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.get_clean_text",
                new_callable=AsyncMock,
                return_value=long_text,
            ),
        ):
            result = await manager._extract_company_description()

        assert result is not None
        assert len(result) > 20

    @pytest.mark.asyncio
    async def test_strips_more_button_text(self, manager):
        mock_element = AsyncMock()
        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_element_safely",
                new_callable=AsyncMock,
                return_value=mock_element,
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.get_clean_text",
                new_callable=AsyncMock,
                return_value="We are a great company building great products… more",
            ),
        ):
            result = await manager._extract_company_description()

        assert result is not None
        assert "… more" not in result

    @pytest.mark.asyncio
    async def test_returns_none_when_no_element(self, manager):
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.find_element_safely",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await manager._extract_company_description()

        assert result is None


class TestCheckApplyButton:
    @pytest.mark.asyncio
    async def test_returns_empty_string_for_easy_apply(self, manager):
        mock_button = AsyncMock()
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
            new_callable=AsyncMock,
            return_value=[mock_button],
        ):
            result = await manager._check_apply_button()

        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_buttons(self, manager):
        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await manager._check_apply_button()

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_url_for_external_apply(self, manager):
        mock_button = AsyncMock()

        def find_elements_side_effect(page, selector, by):
            if "Easy Apply" in selector:
                return []
            return [mock_button]

        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                side_effect=find_elements_side_effect,
            ),
            patch.object(
                manager,
                "_get_button_link",
                new_callable=AsyncMock,
                return_value="https://external-site.com/apply",
            ),
        ):
            result = await manager._check_apply_button()

        assert result == "https://external-site.com/apply"


class TestGoToNextPage:
    @pytest.mark.asyncio
    async def test_targets_second_visible_page_after_first_page(self, manager):
        manager.page_num = 0
        attempted_selectors = []

        async def safe_click_side_effect(page, selector, timeout=10000):
            attempted_selectors.append(selector)
            return True

        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.safe_click",
                side_effect=safe_click_side_effect,
            ),
            patch("src.job_manager.linkedin.job_manager_linkedin.emit_event"),
            patch("src.job_manager.linkedin.job_manager_linkedin.async_pause"),
        ):
            result = await manager._go_to_next_page()

        assert result is True
        assert manager.page_num == 1
        assert attempted_selectors[0] == (
            "button[aria-label='Page 2']:not([disabled]):not([aria-current='page'])"
        )

    @pytest.mark.asyncio
    async def test_returns_true_and_increments_page_on_success(self, manager):
        manager.page_num = 1
        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.safe_click",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch("src.job_manager.linkedin.job_manager_linkedin.emit_event"),
            patch("src.job_manager.linkedin.job_manager_linkedin.async_pause"),
        ):
            result = await manager._go_to_next_page()

        assert result is True
        assert manager.page_num == 2

    @pytest.mark.asyncio
    async def test_returns_false_when_no_button_found(self, manager):
        manager.page_num = 1
        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.safe_click",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_element_safely",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("src.job_manager.linkedin.job_manager_linkedin.emit_event"),
        ):
            result = await manager._go_to_next_page()

        assert result is False
        assert manager.page_num == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_element_click(self, manager):
        manager.page_num = 0
        mock_element = AsyncMock()
        mock_element.click = AsyncMock()

        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.safe_click",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_element_safely",
                new_callable=AsyncMock,
                return_value=mock_element,
            ),
            patch("src.job_manager.linkedin.job_manager_linkedin.emit_event"),
            patch("src.job_manager.linkedin.job_manager_linkedin.async_pause"),
        ):
            result = await manager._go_to_next_page()

        assert result is True
        mock_element.click.assert_called_once()


class TestEasyApply:
    @pytest.mark.asyncio
    async def test_delegates_to_linkedin_easy_applier(self, manager, test_job):
        mock_applier = AsyncMock()
        mock_applier.apply_to_job = AsyncMock(
            return_value=(("Success", ""), "/tmp/resumes/generated.pdf")
        )

        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.LinkedInEasyApplier",
            return_value=mock_applier,
        ):
            result = await manager.easy_apply(test_job)

        assert result == ("Success", "")
        mock_applier.apply_to_job.assert_called_once_with(test_job)
        assert manager.submitted_resume_path == "/tmp/resumes/generated.pdf"

    @pytest.mark.asyncio
    async def test_sets_page_on_applier(self, manager, test_job):
        mock_applier = AsyncMock()
        mock_applier.apply_to_job = AsyncMock(return_value=("Skip", ""))
        mock_applier.submitted_resume_path = None

        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.LinkedInEasyApplier",
            return_value=mock_applier,
        ):
            await manager.easy_apply(test_job)

        mock_applier.set_page.assert_called_once_with(manager.page)


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
        manager.job_blacklist = []
        manager.pause_checker = None

    @pytest.mark.asyncio
    async def test_skips_blacklisted_company(self, manager, mock_page, test_job):
        self._setup_manager(manager)
        manager.job_blacklist = ["tech corp"]
        new_page = AsyncMock()
        new_page.url = LINKEDIN_JOB_URL
        mock_page.context.new_page = AsyncMock(return_value=new_page)

        with (
            patch.object(
                manager,
                "_get_detailed_job_description",
                new_callable=AsyncMock,
                return_value=test_job,
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.async_pause",
                new_callable=AsyncMock,
            ),
            patch.object(manager, "_handle_apply_result", new_callable=AsyncMock),
        ):
            result = await manager.apply_job({"url": LINKEDIN_JOB_URL})

        assert result == "Skip"

    @pytest.mark.asyncio
    async def test_skips_already_seen_job(self, manager, mock_page, test_job):
        self._setup_manager(manager)
        manager.success_companies = {
            "Tech Corp": [{"job_title": "Software Engineer", "url": LINKEDIN_JOB_URL}]
        }
        new_page = AsyncMock()
        new_page.url = LINKEDIN_JOB_URL
        mock_page.context.new_page = AsyncMock(return_value=new_page)

        with (
            patch.object(
                manager,
                "_get_detailed_job_description",
                new_callable=AsyncMock,
                return_value=test_job,
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.async_pause",
                new_callable=AsyncMock,
            ),
            patch.object(manager, "_handle_apply_result", new_callable=AsyncMock),
            patch("src.job_manager.linkedin.job_manager_linkedin.COLLECT_INFO_MODE", False),
        ):
            result = await manager.apply_job({"url": LINKEDIN_JOB_URL})

        assert result == "Skip"

    @pytest.mark.asyncio
    async def test_returns_skip_for_invalid_job(self, manager, mock_page):
        self._setup_manager(manager)
        empty_job = Job()
        new_page = AsyncMock()
        new_page.url = LINKEDIN_JOB_URL
        mock_page.context.new_page = AsyncMock(return_value=new_page)

        with (
            patch.object(
                manager,
                "_get_detailed_job_description",
                new_callable=AsyncMock,
                return_value=empty_job,
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.async_pause",
                new_callable=AsyncMock,
            ),
            patch.object(manager, "_handle_apply_result", new_callable=AsyncMock),
        ):
            result = await manager.apply_job({"url": LINKEDIN_JOB_URL})

        assert result == "Skip"

    @pytest.mark.asyncio
    async def test_returns_limit_when_max_applies_reached(self, manager, mock_page, test_job):
        self._setup_manager(manager)
        manager.success_applies_num = 10
        manager.max_applies_num = 10
        new_page = AsyncMock()
        new_page.url = LINKEDIN_JOB_URL
        mock_page.context.new_page = AsyncMock(return_value=new_page)

        mock_llm = MagicMock()
        mock_llm.job_is_interesting.return_value = (True, 80, "Great fit")
        mock_llm.set_job = MagicMock()
        manager.llm_answerer_component = mock_llm

        with (
            patch.object(
                manager,
                "_get_detailed_job_description",
                new_callable=AsyncMock,
                return_value=test_job,
            ),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.async_pause",
                new_callable=AsyncMock,
            ),
            patch.object(
                manager, "easy_apply", new_callable=AsyncMock, return_value=("Success", "")
            ),
            patch.object(manager, "_handle_apply_result", new_callable=AsyncMock),
            patch.object(manager, "_extract_skills_from_vacancy", return_value="Python"),
            patch.object(manager, "_update_skill_stat"),
            patch("src.job_manager.linkedin.job_manager_linkedin.COLLECT_INFO_MODE", False),
            patch("src.job_manager.linkedin.job_manager_linkedin.MONKEY_MODE", False),
            patch("src.job_manager.linkedin.job_manager_linkedin.EASY_APPLY_ONLY_MODE", True),
        ):
            result = await manager.apply_job({"url": LINKEDIN_JOB_URL})

        assert result == "Limit"
