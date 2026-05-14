from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.job_manager.linkedin.easy_applier_linkedin import LinkedInEasyApplier
from src.job_manager.linkedin.easy_applier_linkedin import EASY_APPLY_FORM_SECTION_SELECTORS
from src.pydantic_models.job_models import Job

MODULE = "src.job_manager.linkedin.easy_applier_linkedin"


@pytest.fixture
def easy_applier():
    page = MagicMock()
    page.wait_for_selector = AsyncMock()
    page.locator.return_value.all = AsyncMock(return_value=[])

    with (
        patch(f"{MODULE}.get_ready_made_resume", return_value=None),
        patch.object(LinkedInEasyApplier, "_load_questions", return_value=[]),
    ):
        return LinkedInEasyApplier(
            page=page,
            gpt_answerer=MagicMock(),
            resume_anonymizer=MagicMock(),
            resume_generator_manager=MagicMock(),
            pause_checker=None,
            answers_file=Path("answers.yaml"),
            resume_dir=Path("resume"),
            cover_letter_dir=Path("cover_letters"),
            test_mode=True,
        )


class TestEasyApplyButtonDetection:
    @pytest.mark.asyncio
    async def test_find_easy_apply_button_returns_none_when_limit_reached(self, easy_applier):
        job = Job(
            job_title="VP Engineering",
            company_name="Example",
            url="https://www.linkedin.com/jobs/view/12345",
        )

        with (
            patch.object(easy_applier, "check_for_premium_redirect", new_callable=AsyncMock),
            patch.object(
                easy_applier, "_check_easy_apply_limit", new_callable=AsyncMock
            ) as mock_limit,
        ):
            mock_limit.return_value = True

            result = await easy_applier._find_easy_apply_button(job)

            assert result is None

    @pytest.mark.asyncio
    async def test_find_easy_apply_button_clicks_and_returns_true(self, easy_applier):
        job = Job(
            job_title="VP Engineering",
            company_name="Example",
            url="https://www.linkedin.com/jobs/view/12345",
        )
        button = AsyncMock()
        button.is_visible = AsyncMock(return_value=True)
        button.is_enabled = AsyncMock(return_value=True)
        button.first = AsyncMock()

        with (
            patch.object(easy_applier, "check_for_premium_redirect", new_callable=AsyncMock),
            patch.object(
                easy_applier, "_check_easy_apply_limit", new_callable=AsyncMock
            ) as mock_limit,
            patch(f"{MODULE}.find_elements_safely", new_callable=AsyncMock) as mock_find,
        ):
            mock_limit.return_value = False
            mock_find.return_value = [button]

            result = await easy_applier._find_easy_apply_button(job)

            assert result is True
            button.first.click.assert_awaited_once()
            assert "button" in mock_find.await_args.args[1]

    @pytest.mark.asyncio
    async def test_find_easy_apply_button_recovers_from_feed_update_click(self, easy_applier):
        job = Job(
            job_title="VP Engineering",
            company_name="Example",
            url="https://www.linkedin.com/jobs/view/4413557747",
        )
        wrong_button = AsyncMock()
        wrong_button.is_visible = AsyncMock(return_value=True)
        wrong_button.is_enabled = AsyncMock(return_value=True)
        wrong_button.first = AsyncMock()
        correct_button = AsyncMock()
        correct_button.is_visible = AsyncMock(return_value=True)
        correct_button.is_enabled = AsyncMock(return_value=True)
        correct_button.first = AsyncMock()
        easy_applier.page.url = "https://www.linkedin.com/jobs/view/4413557747"
        easy_applier.page.goto = AsyncMock()

        async def click_wrong_button(*args, **kwargs):
            easy_applier.page.url = "https://www.linkedin.com/feed/update/urn:li:activity:1/"

        async def click_correct_button(*args, **kwargs):
            easy_applier.page.url = "https://www.linkedin.com/jobs/view/4413557747"

        wrong_button.first.click = AsyncMock(side_effect=click_wrong_button)
        correct_button.first.click = AsyncMock(side_effect=click_correct_button)

        with (
            patch.object(easy_applier, "check_for_premium_redirect", new_callable=AsyncMock),
            patch.object(easy_applier, "_check_easy_apply_limit", new_callable=AsyncMock) as mock_limit,
            patch(f"{MODULE}.find_elements_safely", new_callable=AsyncMock) as mock_find,
            patch(f"{MODULE}.async_pause", new_callable=AsyncMock),
        ):
            mock_limit.return_value = False
            mock_find.side_effect = [[wrong_button], [correct_button]]

            result = await easy_applier._find_easy_apply_button(job)

            assert result is True
            easy_applier.page.goto.assert_awaited_once_with(
                job.url, wait_until="domcontentloaded"
            )
            wrong_button.first.click.assert_awaited_once()
            correct_button.first.click.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_find_easy_apply_modal_content_supports_sdui_modal(self, easy_applier):
        modal = AsyncMock()

        async def fake_find(_page, selector, _selector_type="css selector", timeout=None):
            if "data-sdui-screen" in selector and "EasyApply" in selector:
                return modal
            return None

        with patch(f"{MODULE}.find_element_safely", new=AsyncMock(side_effect=fake_find)):
            result = await easy_applier._find_easy_apply_modal_content()

            assert result is modal


class TestNextButtonDetection:
    @pytest.mark.asyncio
    async def test_find_next_or_submit_button_returns_matching_button(self, easy_applier):
        button = AsyncMock()

        with (
            patch(f"{MODULE}.find_elements_safely", new_callable=AsyncMock) as mock_find,
            patch(f"{MODULE}.get_clean_text", new_callable=AsyncMock) as mock_text,
        ):
            mock_find.return_value = [button]
            mock_text.return_value = "Review"

            next_button, button_text = await easy_applier._find_next_or_submit_button()

            assert next_button == button
            assert button_text == "review"

    @pytest.mark.asyncio
    async def test_find_next_or_submit_button_supports_sdui_next_button(self, easy_applier):
        button = AsyncMock()

        with (
            patch(f"{MODULE}.find_elements_safely", new_callable=AsyncMock) as mock_find,
            patch(f"{MODULE}.get_clean_text", new_callable=AsyncMock) as mock_text,
        ):
            mock_find.return_value = [button]
            mock_text.return_value = "Next"

            next_button, button_text = await easy_applier._find_next_or_submit_button()

            assert next_button == button
            assert button_text == "next"
            assert "button:has-text('Next')" in mock_find.await_args.args[1]


class TestSelectorRegistry:
    def test_form_sections_include_sdui_question_container_before_label_fallback(self):
        assert EASY_APPLY_FORM_SECTION_SELECTORS[0].variant == "sdui_question_container"
        assert "div:has(> p):has(> div > div > input)" in EASY_APPLY_FORM_SECTION_SELECTORS[0].selector
