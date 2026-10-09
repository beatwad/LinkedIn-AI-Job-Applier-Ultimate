"""Tests for src/job_manager/linkedin/easy_applier_linkedin.py"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.job_manager.easy_applier import NoInfoException
from src.job_manager.linkedin.easy_applier_linkedin import LinkedInEasyApplier
from src.pydantic_models.job_models import Job, Question

LINKEDIN_DEFAULT_JOB_URL = "https://www.linkedin.com/jobs/view/4410066193"


def build_linkedin_job_url(job_url_or_id: str | None = None) -> str:
    if not job_url_or_id:
        return LINKEDIN_DEFAULT_JOB_URL
    job_url_or_id = job_url_or_id.strip()
    if not job_url_or_id:
        return LINKEDIN_DEFAULT_JOB_URL
    if job_url_or_id.isdigit():
        return f"https://www.linkedin.com/jobs/view/{job_url_or_id}"
    return job_url_or_id


def normalize_test_job_from_parsed_page(parsed_job: Job | None, job_url: str) -> Job:
    job = parsed_job or Job()
    if not job.url:
        job.url = job_url
    if not job.job_title:
        job.job_title = "LinkedIn job"
    if not job.company_name:
        job.company_name = "Unknown company"
    if not job.job_description:
        job.job_description = "LinkedIn vacancy information was not parsed from the page."
    if not job.apply_method:
        job.apply_method = "Easy Apply"
    return job


def collect_apply_result_metadata(easy_applier: object, submitted_resume_path: object) -> dict:
    metadata = {}
    if isinstance(submitted_resume_path, str) and submitted_resume_path:
        metadata["submitted_resume_path"] = submitted_resume_path
    applied_at = getattr(easy_applier, "already_applied_at", None)
    applied_at_text = getattr(easy_applier, "already_applied_at_text", None)
    if isinstance(applied_at, str) and applied_at:
        metadata["applied_at"] = applied_at
    if isinstance(applied_at_text, str) and applied_at_text:
        metadata["applied_at_text"] = applied_at_text
    return metadata


LINKEDIN_JOB_URL = "https://www.linkedin.com/jobs/view/123456"


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.url = LINKEDIN_JOB_URL
    return page


@pytest.fixture
def mock_gpt_answerer():
    gpt = MagicMock()
    gpt.write_cover_letter.return_value = "Dear Hiring Manager, ..."
    gpt.answer_question_textual_wide_range.return_value = "My answer"
    gpt.answer_question_numeric.return_value = "5"
    gpt.select_one_answer_from_options.return_value = "yes"
    gpt.select_many_answers_from_options.return_value = ["yes"]
    return gpt


@pytest.fixture
def mock_resume_anonymizer():
    anon = MagicMock()
    anon.deanonymize_text = lambda text: text
    return anon


@pytest.fixture
def applier(mock_page, mock_gpt_answerer, mock_resume_anonymizer, tmp_path):
    resume_dir = tmp_path / "resumes"
    resume_dir.mkdir()
    cover_dir = tmp_path / "cover_letters"
    cover_dir.mkdir()
    answers_file = tmp_path / "answers.yaml"

    with patch(
        "src.job_manager.linkedin.easy_applier_linkedin.get_ready_made_resume", return_value=None
    ):
        with patch(
            "src.job_manager.linkedin.easy_applier_linkedin.get_ready_made_photo", return_value=None
        ):
            with patch(
                "src.job_manager.linkedin.easy_applier_linkedin.load_yaml_file", return_value=None
            ):
                inst = LinkedInEasyApplier(
                    page=mock_page,
                    gpt_answerer=mock_gpt_answerer,
                    resume_anonymizer=mock_resume_anonymizer,
                    resume_generator_manager=AsyncMock(),
                    pause_checker=None,
                    answers_file=answers_file,
                    resume_dir=resume_dir,
                    cover_letter_dir=cover_dir,
                    test_mode=False,
                )
    inst.current_job = Job(job_title="Engineer", company_name="TestCorp", url=LINKEDIN_JOB_URL)
    return inst


@pytest.fixture
def test_job():
    return Job(job_title="Engineer", company_name="TestCorp", url=LINKEDIN_JOB_URL)


class TestInit:
    def test_sets_attributes(self, applier, mock_page):
        assert applier.page is mock_page
        assert applier.test_mode is False
        assert applier.all_questions == []
        assert applier.previous_question_texts == []
        assert applier.submitted_resume_path is None

    def test_generated_dirs_are_subdirs(self, applier):
        assert applier.generated_resume_dir.name == "generated_resumes"
        assert applier.generated_cover_letter_dir.name == "generated_cover_letters"


class TestDirectScriptHelpers:
    def test_builds_job_url_from_id(self):
        assert build_linkedin_job_url("4410514476") == (
            "https://www.linkedin.com/jobs/view/4410514476"
        )

    def test_preserves_full_job_url(self):
        url = "https://www.linkedin.com/jobs/view/4410514476"
        assert build_linkedin_job_url(url) == url

    def test_normalizes_parsed_job_without_overwriting_real_fields(self):
        parsed_job = Job(
            job_title="Head of AI",
            company_name="Involved Solutions",
            url="https://www.linkedin.com/jobs/view/4410514476",
            job_description="Parsed description",
        )

        job = normalize_test_job_from_parsed_page(
            parsed_job, "https://www.linkedin.com/jobs/view/4410514476"
        )

        assert job.job_title == "Head of AI"
        assert job.company_name == "Involved Solutions"
        assert job.job_description == "Parsed description"
        assert job.apply_method == "Easy Apply"

    def test_normalizes_missing_parsed_fields_with_generic_fallbacks(self):
        job = normalize_test_job_from_parsed_page(
            Job(), "https://www.linkedin.com/jobs/view/4410514476"
        )

        assert job.url == "https://www.linkedin.com/jobs/view/4410514476"
        assert job.job_title == "LinkedIn job"
        assert job.company_name == "Unknown company"
        assert job.job_description
        assert job.apply_method == "Easy Apply"

    def test_collect_apply_result_metadata(self):
        applier = MagicMock()
        applier.already_applied_at = "2026-05-07T10:00:00"
        applier.already_applied_at_text = "5 hours ago"

        assert collect_apply_result_metadata(applier, "/tmp/resume.pdf") == {
            "submitted_resume_path": "/tmp/resume.pdf",
            "applied_at": "2026-05-07T10:00:00",
            "applied_at_text": "5 hours ago",
        }

    def test_collect_apply_result_metadata_omits_empty_values(self):
        applier = MagicMock()
        applier.already_applied_at = None
        applier.already_applied_at_text = None

        assert collect_apply_result_metadata(applier, None) == {}


class TestCheckForPremiumRedirect:
    @pytest.mark.asyncio
    async def test_no_redirect(self, applier, test_job):
        applier.page.url = LINKEDIN_JOB_URL
        with patch("src.job_manager.linkedin.easy_applier_linkedin.async_pause"):
            result = await applier.check_for_premium_redirect(test_job)
        assert result is False

    @pytest.mark.asyncio
    async def test_redirect_resolved_after_one_attempt(self, applier, test_job):
        applier.page.url = "https://www.linkedin.com/premium/something"

        async def set_url(*args, **kwargs):
            applier.page.url = LINKEDIN_JOB_URL

        applier.page.goto = AsyncMock(side_effect=set_url)
        with patch("src.job_manager.linkedin.easy_applier_linkedin.async_pause"):
            result = await applier.check_for_premium_redirect(test_job)
        assert result is True

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts(self, applier, test_job):
        applier.page.url = "https://www.linkedin.com/premium/something"
        applier.page.goto = AsyncMock()
        with patch("src.job_manager.linkedin.easy_applier_linkedin.async_pause"):
            with pytest.raises(Exception, match="Redirected to linkedIn Premium page"):
                await applier.check_for_premium_redirect(test_job, max_attempts=2)


class TestCheckEasyApplyLimit:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_limit_error(self, applier):
        with patch(
            "src.job_manager.linkedin.easy_applier_linkedin.find_elements_safely",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await applier._check_easy_apply_limit()
        assert not result

    @pytest.mark.asyncio
    async def test_returns_true_when_limit_text_found(self, applier):
        mock_element = AsyncMock()
        mock_element.text_content = AsyncMock(
            return_value="You've reached today's Easy Apply limit"
        )
        with patch(
            "src.job_manager.linkedin.easy_applier_linkedin.find_elements_safely",
            new_callable=AsyncMock,
            return_value=[mock_element],
        ):
            result = await applier._check_easy_apply_limit()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, applier):
        with patch(
            "src.job_manager.linkedin.easy_applier_linkedin.find_elements_safely",
            new_callable=AsyncMock,
            side_effect=Exception("network error"),
        ):
            with patch("src.job_manager.linkedin.easy_applier_linkedin.debug_capture"):
                result = await applier._check_easy_apply_limit()
        assert not result


class TestApplyToJob:
    @pytest.mark.asyncio
    async def test_skips_when_limit_reached(self, applier, test_job):
        applier._check_easy_apply_limit = AsyncMock(return_value=True)
        result = await applier.apply_to_job(test_job)
        assert result[0][0] == "Limit"

    @pytest.mark.asyncio
    async def test_delegates_to_job_easy_apply(self, applier, test_job):
        applier._check_easy_apply_limit = AsyncMock(return_value=False)
        applier.submitted_resume_path = None
        applier.job_easy_apply = AsyncMock(return_value=("Success", ""))
        with patch("src.job_manager.linkedin.easy_applier_linkedin.emit_event"):
            result = await applier.apply_to_job(test_job)
        assert result == (("Success", ""), None)

    @pytest.mark.asyncio
    async def test_reraises_exception(self, applier, test_job):
        applier._check_easy_apply_limit = AsyncMock(return_value=False)
        applier.job_easy_apply = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("src.job_manager.linkedin.easy_applier_linkedin.emit_event"):
            with patch("src.job_manager.linkedin.easy_applier_linkedin.debug_capture"):
                with pytest.raises(RuntimeError, match="boom"):
                    await applier.apply_to_job(test_job)


class TestJobEasyApply:
    @pytest.mark.asyncio
    async def test_returns_skip_when_no_easy_apply_button(self, applier, test_job):
        applier._is_already_applied = AsyncMock(return_value=False)
        applier._find_easy_apply_button = AsyncMock(return_value=False)
        with patch("src.job_manager.linkedin.easy_applier_linkedin.async_pause"):
            result = await applier.job_easy_apply(test_job)
        assert result[0] == "Skip"

    @pytest.mark.asyncio
    async def test_returns_skip_when_already_applied_status_is_present(self, applier, test_job):
        applier._is_already_applied = AsyncMock(return_value=True)

        result = await applier.job_easy_apply(test_job)

        assert result == ("Skip", "Already applied to this job")

    @pytest.mark.asyncio
    async def test_returns_success_on_complete_application(self, applier, test_job):
        applier._is_already_applied = AsyncMock(return_value=False)
        applier._find_easy_apply_button = AsyncMock(return_value=True)
        applier._click_continue_applying_button = AsyncMock()
        applier.check_for_premium_redirect = AsyncMock(return_value=False)
        applier._fill_application_form = AsyncMock()
        with patch("src.job_manager.linkedin.easy_applier_linkedin.async_pause"):
            with patch("src.job_manager.linkedin.easy_applier_linkedin.capture_page_screenshot"):
                with patch("src.job_manager.linkedin.easy_applier_linkedin.emit_event"):
                    result = await applier.job_easy_apply(test_job)
        assert result[0] == "Success"

    @pytest.mark.asyncio
    async def test_returns_error_on_unexpected_exception(self, applier, test_job):
        applier._is_already_applied = AsyncMock(return_value=False)
        applier._find_easy_apply_button = AsyncMock(return_value=True)
        applier._click_continue_applying_button = AsyncMock()
        applier.check_for_premium_redirect = AsyncMock(return_value=False)
        applier._fill_application_form = AsyncMock(side_effect=RuntimeError("form error"))
        applier._save_job_application_process = AsyncMock()
        with patch("src.job_manager.linkedin.easy_applier_linkedin.async_pause"):
            with patch("src.job_manager.linkedin.easy_applier_linkedin.capture_page_screenshot"):
                with patch("src.job_manager.linkedin.easy_applier_linkedin.debug_capture"):
                    result = await applier.job_easy_apply(test_job)
        assert result[0] == "Error"
        assert "form error" in result[1]

    @pytest.mark.asyncio
    async def test_returns_skip_when_easy_apply_dialog_does_not_open(self, applier, test_job):
        applier._is_already_applied = AsyncMock(return_value=False)
        applier._find_easy_apply_button = AsyncMock(return_value=True)
        applier._click_continue_applying_button = AsyncMock()
        applier.check_for_premium_redirect = AsyncMock(return_value=False)
        applier._fill_application_form = AsyncMock(
            side_effect=NoInfoException("Easy Apply dialog did not open")
        )
        with patch("src.job_manager.linkedin.easy_applier_linkedin.async_pause"):
            with patch("src.job_manager.linkedin.easy_applier_linkedin.capture_page_screenshot"):
                with patch("src.job_manager.linkedin.easy_applier_linkedin.debug_capture"):
                    result = await applier.job_easy_apply(test_job)

        assert result[0] == "Skip"
        assert "Easy Apply dialog did not open" in result[1]


class TestNextOrSubmit:
    @pytest.mark.asyncio
    async def test_returns_false_on_next_button(self, applier):
        mock_button = AsyncMock()
        applier._find_next_or_submit_button = AsyncMock(return_value=(mock_button, "next"))
        applier._check_and_fix_errors = AsyncMock(return_value=True)
        result = await applier._next_or_submit()
        assert result is False

    @pytest.mark.asyncio
    async def test_discards_in_test_mode(self, applier):
        applier.test_mode = True
        mock_button = AsyncMock()
        applier._find_next_or_submit_button = AsyncMock(
            return_value=(mock_button, "submit application")
        )
        applier._unfollow_company = AsyncMock()
        applier._discard_application = AsyncMock()
        with patch("src.job_manager.linkedin.easy_applier_linkedin.async_pause"):
            result = await applier._next_or_submit()
        assert result is True
        applier._discard_application.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_when_no_button_found(self, applier):
        applier._find_next_or_submit_button = AsyncMock(return_value=(None, None))
        with pytest.raises(Exception, match="Could not find"):
            await applier._next_or_submit()


class TestCheckAndFixErrors:
    @pytest.mark.asyncio
    async def test_returns_true_when_no_errors(self, applier):
        mock_button = AsyncMock()
        applier._find_all_form_errors = AsyncMock(return_value=[])
        with patch("src.job_manager.linkedin.easy_applier_linkedin.async_pause"):
            result = await applier._check_and_fix_errors(mock_button)
        assert result is True

    @pytest.mark.asyncio
    async def test_raises_after_max_attempts_with_errors(self, applier):
        mock_button = AsyncMock()
        applier._find_all_form_errors = AsyncMock(return_value=["Field is required"])
        applier._fill_textbox_question_errors = AsyncMock()
        applier._find_next_or_submit_button = AsyncMock(return_value=(mock_button, "next"))
        with patch("src.job_manager.linkedin.easy_applier_linkedin.async_pause"):
            with pytest.raises(Exception, match="Failed to answer questions"):
                await applier._check_and_fix_errors(mock_button)

    @pytest.mark.asyncio
    async def test_fixes_errors_then_succeeds(self, applier):
        mock_button = AsyncMock()
        # First call returns errors, second returns none
        applier._find_all_form_errors = AsyncMock(side_effect=[["error"], []])
        applier._fill_textbox_question_errors = AsyncMock()
        applier._find_next_or_submit_button = AsyncMock(return_value=(mock_button, "next"))
        with patch("src.job_manager.linkedin.easy_applier_linkedin.async_pause"):
            result = await applier._check_and_fix_errors(mock_button)
        assert result is True


class TestIsUploadField:
    @pytest.mark.asyncio
    async def test_detects_file_input(self, applier):
        element = MagicMock()
        file_inputs_loc = AsyncMock()
        file_inputs_loc.all = AsyncMock(return_value=[MagicMock()])
        upload_containers_loc = AsyncMock()
        upload_containers_loc.all = AsyncMock(return_value=[])
        upload_buttons_loc = AsyncMock()
        upload_buttons_loc.all = AsyncMock(return_value=[])
        element.locator = MagicMock(
            side_effect=lambda sel: {
                "xpath=.//input[@type='file']": file_inputs_loc,
                ".js-jobs-document-upload__container": upload_containers_loc,
                ".jobs-document-upload__upload-button": upload_buttons_loc,
            }[sel]
        )
        result = await applier._is_upload_field(element)
        assert result is True

    @pytest.mark.asyncio
    async def test_not_upload_when_no_indicators(self, applier):
        element = MagicMock()
        empty_loc = AsyncMock()
        empty_loc.all = AsyncMock(return_value=[])
        element.locator = MagicMock(return_value=empty_loc)
        result = await applier._is_upload_field(element)
        assert result is False


def _radio_element(aria_labels):
    radios = MagicMock()
    radios.evaluate_all = AsyncMock(return_value=aria_labels)
    element = MagicMock()
    element.locator = MagicMock(return_value=radios)
    return element


class TestResumePicker:
    @pytest.mark.asyncio
    async def test_detects_radio_group_of_resume_files(self, applier):
        element = _radio_element(["resume.pdf", "Alex_CV.PDF", "cv.docx"])
        assert await applier._is_resume_picker(element) is True

    @pytest.mark.asyncio
    async def test_regular_radio_question_is_not_picker(self, applier):
        element = _radio_element(["Yes", "No"])
        assert await applier._is_resume_picker(element) is False

    @pytest.mark.asyncio
    async def test_uploads_resume_through_file_chooser(self, applier, tmp_path):
        ready_made_resume = tmp_path / "existing.pdf"
        ready_made_resume.write_bytes(b"existing")
        applier.ready_made_resume_path = ready_made_resume

        trigger = AsyncMock()
        upload_button = MagicMock()
        upload_button.count = AsyncMock(return_value=1)
        upload_button.first = trigger
        dialog = MagicMock()
        dialog.count = AsyncMock(return_value=1)
        dialog.get_by_role = MagicMock(return_value=upload_button)
        applier.page.locator = MagicMock(return_value=MagicMock(first=dialog))

        chooser = AsyncMock()

        class ChooserInfo:
            async def _value(self):
                return chooser

            @property
            def value(self):
                return self._value()

        chooser_ctx = MagicMock()
        chooser_ctx.__aenter__ = AsyncMock(return_value=ChooserInfo())
        chooser_ctx.__aexit__ = AsyncMock(return_value=False)
        applier.page.expect_file_chooser = MagicMock(return_value=chooser_ctx)

        job = Job(job_title="Engineer", company_name="Tech")
        with patch("src.job_manager.easy_applier.async_pause", new_callable=AsyncMock):
            result = await applier._upload_resume_via_picker(job)

        expected_path = os.path.abspath(str(ready_made_resume))
        assert result is True
        trigger.click.assert_awaited_once()
        chooser.set_files.assert_awaited_once_with(expected_path)
        assert applier.submitted_resume_path == expected_path

    @pytest.mark.asyncio
    async def test_falls_back_to_radio_selection_when_upload_fails(self, applier):
        element = MagicMock()
        applier._is_resume_picker = AsyncMock(return_value=True)
        applier._upload_resume_via_picker = AsyncMock(return_value=False)
        applier._process_form_section = AsyncMock()

        await applier._process_form_element(element, Job(job_title="E", company_name="T"), set())

        applier._process_form_section.assert_awaited_once_with(element)


class TestAlreadyAppliedDetection:
    @pytest.mark.asyncio
    async def test_detects_application_submitted_status(self, applier):
        with patch(
            "src.job_manager.linkedin.easy_applier_linkedin.find_element_safely",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ):
            result = await applier._is_already_applied()

        assert result is True

    @pytest.mark.asyncio
    async def test_extracts_application_submitted_date(self, applier):
        date_locator = AsyncMock()
        date_locator.count = AsyncMock(return_value=1)
        date_locator.inner_text = AsyncMock(return_value="18 hours ago")
        date_locator_container = MagicMock()
        date_locator_container.first = date_locator
        submitted_element = MagicMock()
        submitted_element.locator.return_value = date_locator_container

        with patch(
            "src.job_manager.linkedin.easy_applier_linkedin.find_element_safely",
            new_callable=AsyncMock,
            return_value=submitted_element,
        ) as mock_find:
            result = await applier._is_already_applied()

        assert result is True
        assert applier.already_applied_at_text == "18 hours ago"
        assert applier.already_applied_at is not None
        assert not mock_find.call_args.args[1].startswith("xpath=")

    @pytest.mark.asyncio
    async def test_returns_false_when_application_status_missing(self, applier):
        with patch(
            "src.job_manager.linkedin.easy_applier_linkedin.find_element_safely",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await applier._is_already_applied()

        assert result is False


class TestUploadFields:
    @pytest.mark.asyncio
    async def test_generates_resume_even_when_ready_made_resume_exists(self, applier, tmp_path):
        ready_made_resume = tmp_path / "existing.pdf"
        ready_made_resume.write_bytes(b"existing")
        applier.ready_made_resume_path = ready_made_resume

        upload_element = AsyncMock()
        upload_element.get_attribute = AsyncMock(return_value="resume-upload")
        upload_element.evaluate = AsyncMock()
        upload_element.set_input_files = AsyncMock()

        parent = AsyncMock()
        parent.text_content = AsyncMock(return_value="Resume")
        upload_element.locator = MagicMock(return_value=MagicMock(first=parent))

        element = MagicMock()
        upload_locator = MagicMock()
        upload_locator.all = AsyncMock(return_value=[upload_element])
        element.locator = MagicMock(return_value=upload_locator)

        applier._create_and_upload_resume = AsyncMock()
        job = Job(job_title="Engineer", company_name="Tech")

        with patch(
            "src.job_manager.linkedin.easy_applier_linkedin.find_element_safely",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await applier._handle_upload_fields(element, job, set())

        applier._create_and_upload_resume.assert_called_once_with(upload_element, job)
        upload_element.set_input_files.assert_not_called()

    @pytest.mark.asyncio
    async def test_records_ready_made_resume_path_when_uploaded(self, applier, tmp_path):
        ready_made_resume = tmp_path / "existing.pdf"
        ready_made_resume.write_bytes(b"existing")
        applier.ready_made_resume_path = ready_made_resume
        applier.resume_generator_manager = None

        upload_element = AsyncMock()
        upload_element.get_attribute = AsyncMock(return_value="resume-upload")
        upload_element.evaluate = AsyncMock()
        upload_element.set_input_files = AsyncMock()

        parent = AsyncMock()
        parent.text_content = AsyncMock(return_value="Resume")
        upload_element.locator = MagicMock(return_value=MagicMock(first=parent))

        element = MagicMock()
        upload_locator = MagicMock()
        upload_locator.all = AsyncMock(return_value=[upload_element])
        element.locator = MagicMock(return_value=upload_locator)

        job = Job(job_title="Engineer", company_name="Tech")

        with (
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.find_element_safely",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.async_pause",
                new_callable=AsyncMock,
            ),
        ):
            await applier._handle_upload_fields(element, job, set())

        expected_path = os.path.abspath(str(ready_made_resume.resolve()))
        upload_element.set_input_files.assert_called_once_with(expected_path)
        assert applier.submitted_resume_path == expected_path

    @pytest.mark.asyncio
    async def test_uploads_photo_when_image_file_input_is_detected(self, applier):
        upload_element = AsyncMock()

        async def get_attribute_side_effect(name):
            if name == "id":
                return "photo-upload"
            if name == "accept":
                return "image/jpg,image/jpeg,image/gif,image/png"
            return None

        upload_element.get_attribute.side_effect = get_attribute_side_effect
        upload_element.evaluate = AsyncMock()

        parent = AsyncMock()
        parent.text_content = AsyncMock(return_value="Photo")
        upload_element.locator = MagicMock(return_value=MagicMock(first=parent))

        element = MagicMock()
        upload_locator = MagicMock()
        upload_locator.all = AsyncMock(return_value=[upload_element])
        element.locator = MagicMock(return_value=upload_locator)

        applier._create_and_upload_photo = AsyncMock()
        job = Job(job_title="Engineer", company_name="Tech")

        with patch(
            "src.job_manager.linkedin.easy_applier_linkedin.find_element_safely",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await applier._handle_upload_fields(element, job, set())

        applier._create_and_upload_photo.assert_called_once_with(upload_element, job)


class TestCreateAndUploadPhoto:
    @pytest.mark.asyncio
    async def test_uploads_ready_made_photo_when_configured(self, applier, tmp_path):
        ready_made_photo = tmp_path / "profile.jpg"
        ready_made_photo.write_bytes(b"photo-bytes")
        applier.ready_made_photo_path = ready_made_photo

        upload_element = AsyncMock()
        upload_element.set_input_files = AsyncMock()
        job = Job(job_title="Engineer", company_name="Tech")

        with patch(
            "src.job_manager.linkedin.easy_applier_linkedin.async_pause",
            new_callable=AsyncMock,
        ):
            await applier._create_and_upload_photo(upload_element, job)

        upload_element.set_input_files.assert_called_once_with(
            os.path.abspath(str(ready_made_photo.resolve()))
        )

    @pytest.mark.asyncio
    async def test_rejects_ready_made_photo_with_unsupported_extension(self, applier, tmp_path):
        ready_made_photo = tmp_path / "profile.bmp"
        ready_made_photo.write_bytes(b"photo-bytes")
        applier.ready_made_photo_path = ready_made_photo

        upload_element = AsyncMock()
        job = Job(job_title="Engineer", company_name="Tech")

        with pytest.raises(ValueError, match="Photo file format is not allowed"):
            await applier._create_and_upload_photo(upload_element, job)


class TestDeduplicateQuestionText:
    def test_deduplicates_repeated_string(self, applier):
        text = "hello worldhello world"
        result = applier._deduplicate_question_text(text)
        assert result == "hello world"

    def test_deduplicates_newline_duplicates(self, applier):
        text = "question\nquestion"
        result = applier._deduplicate_question_text(text)
        assert result == "question"

    def test_leaves_unique_text_intact(self, applier):
        text = "line one\nline two"
        result = applier._deduplicate_question_text(text)
        assert result == "line one\nline two"

    def test_empty_string(self, applier):
        result = applier._deduplicate_question_text("")
        assert result == ""


class TestIsNumericField:
    @pytest.mark.asyncio
    async def test_detects_number_type(self, applier):
        field = AsyncMock()
        field.get_attribute = AsyncMock(side_effect=lambda attr: "number" if attr == "type" else "")
        result = await applier._is_numeric_field(field)
        assert result is True

    @pytest.mark.asyncio
    async def test_detects_numeric_in_id(self, applier):
        field = AsyncMock()
        field.get_attribute = AsyncMock(
            side_effect=lambda attr: "text" if attr == "type" else "numeric-experience"
        )
        result = await applier._is_numeric_field(field)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_for_plain_text(self, applier):
        field = AsyncMock()
        field.get_attribute = AsyncMock(
            side_effect=lambda attr: "text" if attr == "type" else "first-name"
        )
        result = await applier._is_numeric_field(field)
        assert result is False

    @pytest.mark.asyncio
    async def test_detects_keyword_in_question_text(self, applier):
        field = AsyncMock()
        field.get_attribute = AsyncMock(side_effect=lambda attr: "text" if attr == "type" else "")
        result = await applier._is_numeric_field(field, "what is your expected salary?")
        assert result is True

    @pytest.mark.asyncio
    async def test_keyword_not_matched_as_substring(self, applier):
        field = AsyncMock()
        field.get_attribute = AsyncMock(side_effect=lambda attr: "text" if attr == "type" else "")
        # "rate" is a substring of "demonstrates" — must not match
        question = "include github code samples and any evaluation or benchmark work that demonstrates your technical rigor."
        result = await applier._is_numeric_field(field, question)
        assert result is False

    @pytest.mark.asyncio
    async def test_keyword_matched_as_whole_word(self, applier):
        field = AsyncMock()
        field.get_attribute = AsyncMock(side_effect=lambda attr: "text" if attr == "type" else "")
        result = await applier._is_numeric_field(field, "what is your hourly rate?")
        assert result is True


class TestSelectDropdownOption:
    @pytest.mark.asyncio
    async def test_selects_by_label_directly(self, applier):
        element = AsyncMock()
        element.select_option = AsyncMock()
        await applier._select_dropdown_option(element, "Full-time")
        element.select_option.assert_called_once_with(label="Full-time", timeout=3000)

    @pytest.mark.asyncio
    async def test_falls_back_to_value_match(self, applier):
        element = AsyncMock()
        element.select_option = AsyncMock(side_effect=[Exception("no label"), None])
        element.locator = MagicMock()
        element.locator.return_value.evaluate_all = AsyncMock(
            return_value=[{"label": "Full-time", "value": "ft"}]
        )
        await applier._select_dropdown_option(element, "Full-time")
        element.select_option.assert_called_with(value="ft")

    @pytest.mark.asyncio
    async def test_normalized_match_ignores_case(self, applier):
        element = AsyncMock()
        element.select_option = AsyncMock(side_effect=[Exception("no label"), None])
        element.locator = MagicMock()
        element.locator.return_value.evaluate_all = AsyncMock(
            return_value=[{"label": "  FULL-TIME  ", "value": "ft"}]
        )
        await applier._select_dropdown_option(element, "full-time")
        element.select_option.assert_called_with(value="ft")


class TestFindAllFormErrors:
    @pytest.mark.asyncio
    async def test_returns_unique_error_texts(self, applier):
        applier.page = MagicMock()
        loc = MagicMock()
        loc.evaluate_all = AsyncMock(
            return_value=["Field is required", "Field is required", "Invalid value"]
        )
        applier.page.locator = MagicMock(return_value=loc)
        errors = await applier._find_all_form_errors()
        assert "Field is required" in errors
        assert "Invalid value" in errors
        assert errors.count("Field is required") == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_errors(self, applier):
        applier.page = MagicMock()
        loc = MagicMock()
        loc.evaluate_all = AsyncMock(return_value=[])
        applier.page.locator = MagicMock(return_value=loc)
        errors = await applier._find_all_form_errors()
        assert errors == []


class TestHandleTermsOfService:
    @pytest.mark.asyncio
    async def test_clicks_terms_of_service_label(self, applier):
        label = AsyncMock()
        label.text_content = AsyncMock(return_value="I agree to the terms of service")
        label.click = AsyncMock()

        checkbox_locator = MagicMock()
        checkbox_locator.all = AsyncMock(return_value=["checkbox"])
        checkbox_locator.first = label

        section = MagicMock()
        section.locator = MagicMock(return_value=checkbox_locator)

        result = await applier._handle_terms_of_service(section)

        assert result is True
        label.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_for_non_tos_label(self, applier):
        label = AsyncMock()
        label.text_content = AsyncMock(return_value="Enter your first name")

        section = MagicMock()
        section.locator = MagicMock(return_value=MagicMock(first=label))

        result = await applier._handle_terms_of_service(section)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, applier):
        section = MagicMock()
        section.locator = MagicMock(side_effect=Exception("locator error"))
        result = await applier._handle_terms_of_service(section)
        assert result is False


class TestFillApplicationForm:
    @pytest.mark.asyncio
    async def test_loops_until_submitted(self, applier, test_job):
        call_count = 0

        async def mock_next_or_submit():
            nonlocal call_count
            call_count += 1
            return call_count >= 2

        applier._fill_up = AsyncMock()
        applier._next_or_submit = mock_next_or_submit
        await applier._fill_application_form(test_job)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_calls_pause_checker(self, applier, test_job):
        pause_checker = AsyncMock()
        applier.pause_checker = pause_checker
        applier._fill_up = AsyncMock()
        applier._next_or_submit = AsyncMock(return_value=True)
        await applier._fill_application_form(test_job)
        pause_checker.assert_called_once()


class TestTextboxCaching:
    @pytest.mark.asyncio
    async def test_reuses_cached_answer_when_field_type_changed(self, applier):
        text_field = AsyncMock()
        text_field.get_attribute = AsyncMock(
            side_effect=lambda attr: "text" if attr == "type" else None
        )
        text_field.fill = AsyncMock()

        label = AsyncMock()
        label.text_content = AsyncMock(return_value="Email Address")

        applier.all_questions = [
            Question(
                question="email address",
                question_type="dropdown",
                answer="  ziad.nahas@gmail.com  ",
            )
        ]

        with (
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[text_field],
            ),
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.find_element_safely",
                new_callable=AsyncMock,
                side_effect=[label],
            ),
            patch.object(applier, "_process_autocomplete_suggestions", new_callable=AsyncMock),
        ):
            result = await applier._find_and_handle_textbox_question(MagicMock())

        assert result is True
        text_field.fill.assert_called_once_with("ziad.nahas@gmail.com")
        applier.gpt_answerer.answer_question_textual_wide_range.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_cached_no_info_and_uses_resume_answer(self, applier):
        text_field = AsyncMock()
        text_field.get_attribute = AsyncMock(
            side_effect=lambda attr: "text" if attr == "type" else None
        )
        text_field.fill = AsyncMock()

        label = AsyncMock()
        label.text_content = AsyncMock(return_value="Middle name")
        section = MagicMock()
        section.locator.return_value.all = AsyncMock(return_value=[label])

        applier.all_questions = [
            Question(question="middle name", question_type="textbox", answer=" No info")
        ]
        applier.gpt_answerer.answer_question_textual_wide_range.return_value = "Example"

        with (
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[text_field],
            ),
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.find_element_safely",
                new_callable=AsyncMock,
                side_effect=[label],
            ),
            patch.object(applier, "_process_autocomplete_suggestions", new_callable=AsyncMock),
        ):
            result = await applier._find_and_handle_textbox_question(section)

        assert result is True
        text_field.fill.assert_called_once_with("Example")
        applier.gpt_answerer.answer_question_textual_wide_range.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_optional_textbox_when_no_info_available(self, applier):
        text_field = AsyncMock()
        text_field.get_attribute = AsyncMock(
            side_effect=lambda attr: "text" if attr == "type" else None
        )
        text_field.fill = AsyncMock()

        label = AsyncMock()
        label.text_content = AsyncMock(return_value="Middle name")
        section = MagicMock()
        section.locator.return_value.all = AsyncMock(return_value=[label])

        applier.gpt_answerer.answer_question_textual_wide_range.return_value = "No info"

        with (
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[text_field],
            ),
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.find_element_safely",
                new_callable=AsyncMock,
                side_effect=[label],
            ),
        ):
            result = await applier._find_and_handle_textbox_question(section)

        assert result is True
        text_field.fill.assert_not_called()

    @pytest.mark.asyncio
    async def test_required_textbox_still_fails_when_no_info_available(self, applier):
        text_field = AsyncMock()
        text_field.get_attribute = AsyncMock(
            side_effect=lambda attr: "true" if attr == "aria-required" else None
        )
        text_field.fill = AsyncMock()

        label = AsyncMock()
        label.text_content = AsyncMock(return_value="Legal first name")
        section = MagicMock()
        section.locator.return_value.all = AsyncMock(return_value=[label])

        applier.gpt_answerer.answer_question_textual_wide_range.return_value = "No info"

        with (
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                return_value=[text_field],
            ),
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.find_element_safely",
                new_callable=AsyncMock,
                side_effect=[label],
            ),
        ):
            with pytest.raises(NoInfoException, match="legal first name"):
                await applier._find_and_handle_textbox_question(section)


class TestDropdownCaching:
    @pytest.mark.asyncio
    async def test_reuses_cached_answer_from_different_field_type(self, applier):
        dropdown = AsyncMock()
        dropdown.get_attribute = AsyncMock(return_value="email-dropdown")
        option_locator = MagicMock()
        option_locator.evaluate_all = AsyncMock(
            return_value=["Select an option", "ziad.nahas@gmail.com"]
        )
        dropdown.locator = MagicMock(return_value=option_locator)

        checked_locator = MagicMock()
        checked_locator.first.text_content = AsyncMock(return_value="Select an option")

        def dropdown_locator(selector):
            if selector == "option:checked":
                return checked_locator
            return option_locator

        dropdown.locator = MagicMock(side_effect=dropdown_locator)

        label = AsyncMock()
        label.text_content = AsyncMock(return_value="Email Address")

        applier.all_questions = [
            Question(
                question="email address", question_type="textbox", answer=" ziad.nahas@gmail.com "
            )
        ]
        applier._select_dropdown_option = AsyncMock()

        async def find_elements(section, selector, by="css selector", **kwargs):
            if selector == "css=select":
                return [dropdown]
            if selector == "label":
                return [label]
            return []

        with (
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                side_effect=find_elements,
            ),
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.find_element_safely",
                new_callable=AsyncMock,
                return_value=label,
            ),
        ):
            result = await applier._find_and_handle_dropdown_question(MagicMock())

        assert result is True
        applier._select_dropdown_option.assert_called_once_with(dropdown, "ziad.nahas@gmail.com")
        applier.gpt_answerer.select_one_answer_from_options.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_already_selected_dropdown_answer(self, applier):
        dropdown = AsyncMock()
        dropdown.get_attribute = AsyncMock(return_value="email-dropdown")
        option_locator = MagicMock()
        option_locator.evaluate_all = AsyncMock(
            return_value=["Select an option", "ziad.nahas@gmail.com"]
        )

        dropdown.locator = MagicMock(return_value=option_locator)
        dropdown.evaluate = AsyncMock(
            return_value={
                "text": "ziad.nahas@gmail.com",
                "index": 1,
                "hasSelectedAttr": True,
            }
        )

        label = AsyncMock()
        label.text_content = AsyncMock(return_value="Email Address")
        applier._save_questions = MagicMock()

        async def find_elements(section, selector, by="css selector", **kwargs):
            if selector == "css=select":
                return [dropdown]
            if selector == "label":
                return [label]
            return []

        with (
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.find_elements_safely",
                new_callable=AsyncMock,
                side_effect=find_elements,
            ),
            patch(
                "src.job_manager.linkedin.easy_applier_linkedin.find_element_safely",
                new_callable=AsyncMock,
                return_value=label,
            ),
        ):
            result = await applier._find_and_handle_dropdown_question(MagicMock())

        assert result is True
        applier.gpt_answerer.select_one_answer_from_options.assert_not_called()
