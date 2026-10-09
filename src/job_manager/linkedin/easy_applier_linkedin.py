import base64
import os
import re
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from playwright.sync_api import Page
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from config.constants import PHOTO_DIR
from config.logger_config import logger
from src.dashboard.runtime import StopRequested, capture_page_screenshot, emit_event
from src.job_manager.easy_applier import BaseEasyApplier, NoInfoException
from src.job_manager.resume_anonymizer import ResumeAnonymizer
from src.llm.llm_manager import GPTAnswerer
from src.pydantic_models.job_models import Job, Question
from src.utils.browser_utils import (
    debug_capture,
    find_element_safely,
    find_elements_safely,
    get_clean_text,
)
from src.utils.utils import (
    async_pause,
    get_ready_made_photo,
    get_ready_made_resume,
    load_yaml_file,
    sanitize_text,
)

# Visible text of a radio or checkbox option, lowercased. New LinkedIn SDUI markup
# renders an empty <label> as a click target and puts the option text either in a
# sibling node of the option's row, or on an aria-label (which may hold the question
# text instead, so it is used only as a last resort).
_OPTION_TEXT_JS = """e => {
    const lbl = e.id ? document.querySelector('label[for="' + CSS.escape(e.id) + '"]') : null;
    let text = (lbl?.textContent || '').trim();
    const options = 'input[type="radio"], [role="radio"], input[type="checkbox"], [role="checkbox"]';
    for (let node = e; !text && node; node = node.parentElement) {
        if (node.querySelectorAll(options).length > 1) break;
        text = (node.textContent || '').trim();
    }
    if (!text) text = (e.closest('[aria-label]')?.getAttribute('aria-label') || '').trim();
    return text.toLowerCase();
}"""


class _FileChooserUpload:
    """Adapter exposing `set_input_files` for upload controls that open a native file chooser.

    LinkedIn's SDUI resume picker has no <input type="file"> in the DOM until its upload
    control is clicked, so the click is deferred until the file is ready to be set.
    """

    def __init__(self, page: Any, trigger: Any):
        self.page = page
        self.trigger = trigger

    async def set_input_files(self, path: str) -> None:
        async with self.page.expect_file_chooser(timeout=5000) as chooser_info:
            await self.trigger.click()
        chooser = await chooser_info.value
        await chooser.set_files(path)


class LinkedInEasyApplier(BaseEasyApplier):
    def __init__(
        self,
        page: Page,
        gpt_answerer: GPTAnswerer,
        resume_anonymizer: ResumeAnonymizer,
        resume_generator_manager,
        pause_checker,
        answers_file: Path,
        resume_dir: Path,
        cover_letter_dir: Path,
        test_mode: bool,
    ):
        logger.info("Initializing LinkedInEasyApplier")
        super().__init__()
        self.page = page
        self.gpt_answerer = gpt_answerer
        self.resume_anonymizer = resume_anonymizer
        self.resume_generator_manager = resume_generator_manager
        self.pause_checker = pause_checker
        self.answers_file = answers_file
        self.resume_dir = resume_dir
        self.generated_resume_dir = Path(resume_dir) / "generated_resumes"
        self.generated_photo_dir = Path(PHOTO_DIR)
        self.generated_cover_letter_dir = Path(cover_letter_dir) / "generated_cover_letters"
        self.ready_made_resume_path = get_ready_made_resume()
        self.ready_made_photo_path = get_ready_made_photo()
        self.all_questions = self._load_questions()
        self.current_job = None
        self.test_mode = test_mode
        self.previous_question_texts = []
        logger.info("LinkedInEasyApplier initialized successfully")

    def set_page(self, page: Page) -> None:
        self.page = page

    async def check_for_premium_redirect(self, job: Job, max_attempts=3) -> bool:
        """Check for LinkedIn premium redirect and attempt to return to job page (async)"""
        current_url = self.page.url
        attempts = 0
        is_redirected = False
        while "linkedin.com/premium" in current_url and attempts < max_attempts:
            logger.warning("Redirected to linkedIn Premium page. Attempting to return to job page.")
            attempts += 1
            is_redirected = True
            await self.page.goto(job.url)
            await async_pause(2, 3)
            current_url = self.page.url

        if "linkedin.com/premium" in current_url:
            logger.error(
                f"Failed to return to job page after {max_attempts} attempts. Cannot apply for the job."
            )
            raise Exception(
                f"Redirected to linkedIn Premium page and failed to return after {max_attempts} attempts. Job application aborted."
            )
        return is_redirected

    async def apply_to_job(self, job: Job) -> Tuple[Tuple[str, str], Any]:
        """
        Starts the process of applying to a job (async).
        :param job: A job object with the job details.
        :return: None
        """
        logger.info(f"Applying to job: {job.job_title} at {job.company_name}")
        emit_event(
            "easy_apply_started",
            f"Easy Apply started for {job.job_title}",
            job_title=job.job_title,
            company_name=job.company_name,
            url=job.url,
        )

        # Check for Easy Apply daily limit before attempting to apply
        if await self._check_easy_apply_limit():
            logger.warning("Easy Apply daily limit reached. Skipping job application.")
            return ("Limit", "Easy Apply daily limit reached. Skipping job application."), None

        try:
            apply_result = await self.job_easy_apply(job)
            return apply_result, self.submitted_resume_path
        except StopRequested:
            raise
        except Exception as e:
            logger.error(f"Failed to apply to job: {job.job_title} at {job.url}, error: {str(e)}")
            await debug_capture(self.page, "apply_to_job_error")
            raise e

    async def job_easy_apply(self, job: Job) -> Tuple[str, str]:
        """Main job application logic (async)"""
        try:
            self.current_job = job
            try:
                await self.page.evaluate("document.activeElement && document.activeElement.blur()")
            except Exception:
                pass
            logger.debug("Focus removed from the active element")
            logger.info("Attempting to click 'Easy Apply' button")
            while True:
                if await self._is_already_applied():
                    return "Skip", "Already applied to this job"
                # Click 'Easy Apply' button
                result = await self._find_easy_apply_button(job)
                if result is False:
                    if await self._is_already_applied():
                        return "Skip", "Already applied to this job"
                    return (
                        "Skip",
                        "No clickable 'Easy Apply' button found, maybe you already applied to this job",
                    )
                logger.debug("'Easy Apply' button clicked successfully")
                await async_pause()
                # Click 'Continue Applying' button if it appears
                await self._click_continue_applying_button()
                await async_pause()
                # Check for premium redirect
                if not await self.check_for_premium_redirect(self.current_job):
                    break
                else:
                    logger.debug("Redirected to premium page, trying again")

            logger.info("Filling out application form")
            await async_pause(2, 3)
            await capture_page_screenshot(self.page, "easy-apply-opened")
            await self._fill_application_form(job)
            logger.info(f"Successfully applied to job: {job.job_title}")
            emit_event(
                "easy_apply_completed",
                f"Easy Apply completed for {job.job_title}",
                job_title=job.job_title,
                company_name=job.company_name,
                url=job.url,
            )
            return "Success", ""

        except NoInfoException as e:
            logger.warning(f"Could not apply to {job.job_title} at {job.company_name}. Reason: {e}")
            return (
                "Skip",
                f"Could not apply to {job.job_title} at {job.company_name}. Reason: {e}",
            )
        except StopRequested:
            raise
        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Failed to apply to job: {job.job_title} at {job.url}, error: {tb_str}")
            await debug_capture(self.page, "job_easy_apply_error")
            await capture_page_screenshot(self.page, "easy-apply-error")
            try:
                await self._save_job_application_process()
            except Exception as e:
                logger.error(f"Failed to save job application process: {e}")
            return "Error", f"Failed to apply to job! Original exception:\nTraceback:\n{tb_str}"

    async def _check_easy_apply_limit(self) -> bool:
        """Check if Easy Apply daily limit has been reached (async)

        Returns:
            bool: True if limit reached, False otherwise
        """
        logger.debug("Checking for Easy Apply daily limit")

        try:
            # Look for the error message indicating daily limit reached
            limit_error_selectors = [
                "//div[contains(@class, 'artdeco-inline-feedback--error')]//span[contains(@class, 'artdeco-inline-feedback__message')]",
                "//div[contains(@class, 'artdeco-inline-feedback--error')]",
                "//*[contains(text(), 'reached today') and contains(text(), 'Easy Apply limit')]",
                "//*[contains(text(), 'daily submissions')]",
            ]

            for selector in limit_error_selectors:
                try:
                    error_elements = await find_elements_safely(self.page, selector, "xpath")
                    if error_elements:
                        for element in error_elements:
                            error_text = (await element.text_content() or "").strip()
                            if error_text and any(
                                phrase in error_text.lower()
                                for phrase in [
                                    "reached today's easy apply limit",
                                    "daily submissions",
                                    "limit daily submissions",
                                    "continue applying tomorrow",
                                ]
                            ):
                                logger.warning(f"Easy Apply daily limit reached: {error_text}")
                                return True
                except Exception as e:
                    logger.debug(f"Error checking selector {selector}: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Error checking Easy Apply limit: {e}")
            await debug_capture(self.page, "easy_apply_limit_check_error")
            return False

    async def _find_easy_apply_button(self, job: Job) -> Any:
        """Find Easy Apply button with retries (async)"""
        logger.debug("Searching for 'Easy Apply' button and try to click")
        attempt = 0

        while attempt < 2:
            await self.check_for_premium_redirect(job)

            # Check for Easy Apply limit before searching for button
            if await self._check_easy_apply_limit():
                logger.warning("Easy Apply daily limit detected while searching for button")
                return None

            easy_apply_selectors = [
                '//button[contains(@aria-label, "Easy Apply")]',
                '//a[contains(., "Apply")]',
            ]

            easy_apply_buttons = []
            for selector in easy_apply_selectors:
                easy_apply_buttons = await find_elements_safely(self.page, selector, "xpath")
                if easy_apply_buttons:
                    break

            for button in easy_apply_buttons:
                try:
                    if not (await button.is_visible() and await button.is_enabled()):
                        logger.debug("Apply button is not visible or enabled")
                        continue
                    await button.first.click(timeout=1000)
                    return True
                except Exception as e:
                    logger.debug(f"Failed to click easy apply button: {e}")

            await self.check_for_premium_redirect(job)

            if attempt == 0:
                logger.debug("Refreshing page to retry finding 'Easy Apply' button")
                await self.page.reload()
                await async_pause(3, 5)
            attempt += 1

        page_url = self.page.url
        logger.warning(
            f"No clickable 'Easy Apply' button found after 2 attempts. page url: {page_url}"
        )
        return False

    async def _click_continue_applying_button(self) -> None:
        """Click continue applying button if present (async)"""
        logger.debug("Searching for 'Continue Applying' button")
        continue_applying_button = await find_element_safely(
            self.page,
            '//*[contains(., "Continue applying") and (self::button or self::a)]',
            "xpath",
        )
        if continue_applying_button:
            await continue_applying_button.click(timeout=1000)

    async def _fill_application_form(self, job: Job):
        """Fill out application form with loop for multi-step forms (async)"""
        logger.info(f"Filling out application form for job: {job.job_title}")
        while True:
            self.previous_question_texts = []
            # Fill out application form
            await self._fill_up(job)
            # Check if execution is paused
            if self.pause_checker:
                await self.pause_checker()
            # Click 'Next' or 'Submit' or 'Confirm' button
            if await self._next_or_submit():
                logger.debug("Application form submitted")
                break

    async def _find_next_or_submit_button(self) -> Any:
        """Find 'Next' or 'Submit' or 'Review' button (async)"""
        logger.info("Finding 'Next' or 'Submit' or 'Review' button")
        target_texts = ["next", "review", "submit application"]

        # Scope the search to the Easy Apply modal so page buttons with the
        # same text (e.g. search result pagination) aren't matched instead
        modal_selectors = [
            '[data-testid="dialog-content"]',  # New SDUI modal container
            ".jobs-easy-apply-modal__content",
            ".artdeco-modal__content",
        ]
        scope = self.page
        for selector in modal_selectors:
            modal_content = await find_element_safely(self.page, selector, "css")
            if modal_content is not None:
                scope = modal_content
                break

        # New SDUI markup renders plain <button> elements with hashed classes;
        # legacy markup exposes the label via the .artdeco-button__text span
        elements = await find_elements_safely(scope, "button, .artdeco-button__text", "css")

        # Filter elements by text content
        next_button = None
        button_text = None

        for element in elements:
            text = await get_clean_text(element)
            if text.lower() in target_texts:
                next_button = element
                button_text = text.lower()
                break

        return next_button, button_text

    async def _next_or_submit(self) -> bool:
        """Click 'Next' or 'Submit' or 'Review' button"""
        logger.info("Clicking 'Next' or 'Submit' or 'Review' button")
        next_button, button_text = await self._find_next_or_submit_button()

        if next_button is None or button_text is None:
            logger.error("No 'Next' or 'Submit' button found on the page")
            raise Exception("Could not find 'Next' or 'Submit' button to proceed with application")

        if "submit application" in button_text:
            logger.debug("Submit button found, submitting application")
            await self._unfollow_company()
            await async_pause()
            if self.test_mode:
                logger.debug("Test mode is enabled, skipping application form submission")
                await self._discard_application()
                return True
            return await self._check_and_fix_errors(next_button)
        await self._check_and_fix_errors(next_button)
        return False

    async def _unfollow_company(self) -> None:
        """Unfollow company checkbox (async)"""
        try:
            follow_checkbox = await find_element_safely(
                self.page,
                "label[for='follow-company-checkbox']",
                "css",
            )
            if follow_checkbox is None:
                # New LinkedIn SDUI markup drops the static id and renders an empty
                # <label>; the toggle is a role="checkbox" div next to "Follow <Company>
                # to stay up to date..." text, checked by default
                follow_checkbox = await find_element_safely(
                    self.page,
                    "//*[@role='checkbox'][@aria-checked='true']"
                    "[contains(translate(., 'FOLLOW', 'follow'), 'follow')]",
                    "xpath",
                )
            if follow_checkbox is None:
                # Newer SDUI markup: a checked <input> carrying the "Follow <Company>..."
                # text as aria-label, followed by an empty <label> click target
                follow_checkbox = await find_element_safely(
                    self.page,
                    "input[type='checkbox'][aria-label^='follow' i]:checked + label",
                    "css",
                )
            if follow_checkbox:
                await follow_checkbox.click(timeout=1000)

        except Exception as e:
            logger.warning(f"Failed to unfollow company: {e}")
            await debug_capture(self.page, "unfollow_company_error")

    async def _check_and_fix_errors(self, next_button: Any) -> bool:
        """Check for errors in the form and try to fix them (async)"""
        logger.info("Checking for errors in the form and trying to fix them")
        await async_pause(1, 2)
        await next_button.click(timeout=1000)
        await async_pause(2, 3)
        attempt = 0
        while attempt < 3:
            error_texts = await self._find_all_form_errors()
            if len(error_texts) > 0:
                logger.info(f"Found {len(error_texts)} errors")
                await self._fill_textbox_question_errors()
                await async_pause(1, 2)
                next_button, _ = await self._find_next_or_submit_button()
                try:
                    await next_button.click(timeout=1000)
                except Exception as e:
                    logger.warning(f"Failed to click next button: {e}")
                    await debug_capture(self.page, "next_button_click_error")
                await async_pause(2, 3)
            else:
                return True
            attempt += 1
        else:
            logger.error(f"Form submission failed with errors: {str(error_texts)}")
            raise Exception(
                f"Failed to answer questions or file upload with errors: {str(error_texts)}"
            )

    async def _discard_application(self) -> None:
        """Discard application (async)"""
        logger.info("Discarding application")
        try:
            dismiss = await find_element_safely(
                self.page, "//*[contains(@class, 'artdeco-modal__dismiss')]", "xpath"
            )
            if dismiss:
                await dismiss.click(timeout=1000)
                await async_pause(2, 3)
            confirm_buttons = self.page.locator(
                "xpath=//*[contains(@class, 'artdeco-modal__confirm-dialog-btn')]"
            )
            if await confirm_buttons.count() > 0:
                await confirm_buttons.first.click(timeout=1000)
                await async_pause(2, 3)
        except Exception as e:
            logger.warning(f"Failed to discard application: {e}")
            await debug_capture(self.page, "discard_application_error")

    async def _save_job_application_process(self) -> None:
        """Save job application process (async)"""
        logger.info("Application not completed. Saving job to My Jobs, In Progess section")
        try:
            dismiss = await find_element_safely(
                self.page, "//*[contains(@class, 'artdeco-modal__dismiss')]", "xpath"
            )
            if dismiss:
                await dismiss.click(timeout=1000)
                await async_pause(2, 3)
            confirm_buttons = self.page.locator(
                "xpath=//*[contains(@class, 'artdeco-modal__confirm-dialog-btn')]"
            )
            if await confirm_buttons.count() > 1:
                await confirm_buttons.nth(1).click(timeout=1000)
                await async_pause(2, 3)
        except Exception as e:
            logger.error(f"Failed to save application process: {e}")
            await debug_capture(self.page, "save_application_error")

    async def _widen_to_question_container(self, fieldset: Any) -> Any:
        """Expand a radio/checkbox <fieldset> to include its question text.

        LinkedIn's new SDUI markup renders the question label as a sibling of the
        <fieldset>, not a descendant, so the fieldset's own text_content() only
        contains the option labels. Climb ancestors until one actually adds text
        beyond the fieldset's own content (i.e. contains the question label).
        """
        container = fieldset
        try:
            own_text = (await container.text_content() or "").strip()
            for _ in range(4):
                parent = container.locator("xpath=..").first
                if await parent.count() == 0:
                    break
                parent_text = (await parent.text_content() or "").strip()
                if parent_text != own_text:
                    return parent
                container = parent
        except Exception as e:
            logger.debug(f"Failed widening fieldset to question container: {e}")
        return container

    async def _widen_to_text_input_container(self, text_field: Any) -> Any:
        """Expand a standalone text/textarea input to include its question text.

        LinkedIn's newer SDUI markup renders some text questions with the question
        text in a sibling <p> instead of a <label>, so climb ancestors until one
        contains a <p> element (the question text), capped to avoid over-widening.
        """
        container = text_field
        try:
            for _ in range(5):
                parent = container.locator("xpath=..").first
                if await parent.count() == 0:
                    break
                container = parent
                if await container.locator("p").count() > 0:
                    break
        except Exception as e:
            logger.debug(f"Failed widening text input to question container: {e}")
        return container

    async def _fill_up(self, job: Job) -> None:
        """Fill up form sections (async)"""
        logger.info(f"Filling up form sections for job: {job.job_title}")

        try:
            # Wait for the Easy Apply modal content to be present with explicit wait
            modal_content = None
            logger.debug("Waiting for Easy Apply modal to appear...")

            # Try to wait for the modal to be visible
            try:
                # Wait up to 10 seconds for the modal to appear
                await self.page.wait_for_selector(
                    '[data-testid="dialog-content"]', state="visible", timeout=10000
                )
                logger.debug("Modal selector found via wait_for_selector")
            except Exception as e:
                logger.warning(f"wait_for_selector failed: {e}")

            # Try multiple selectors to find the modal content
            modal_selectors = [
                '[data-testid="dialog-content"]',  # New SDUI modal container
                ".jobs-easy-apply-modal__content",  # CSS selector
                ".artdeco-modal__content",  # Fallback CSS
                "//*[contains(@class, 'jobs-easy-apply-modal__content')]",  # XPath
            ]

            for selector in modal_selectors:
                selector_type = (
                    "css" if selector.startswith(".") or selector.startswith("[") else "xpath"
                )
                modal_content = await find_element_safely(self.page, selector, selector_type)
                if modal_content is not None:
                    logger.debug(f"Easy Apply modal content found with selector: {selector}")
                    break

            if modal_content is None:
                logger.error("Easy Apply modal content not found on the page with any selector")
                if await self._is_already_applied():
                    raise NoInfoException("Already applied to this job")
                raise NoInfoException("Easy Apply dialog did not open")

            logger.debug("Easy Apply modal content found successfully")

            # Track processed file inputs to avoid duplicate processing
            processed_file_inputs = set()

            # Find all form elements using the correct selectors
            form_elements = await modal_content.locator(".fb-dash-form-element").all()
            logger.debug(f"Found {len(form_elements)} form elements")

            if not form_elements:
                # Fallback to the old selector if new one doesn't work
                form_elements = await modal_content.locator(
                    "xpath=.//*[contains(@class, 'jobs-easy-apply-form-section__group')]"
                ).all()
                logger.debug(
                    f"Fallback: Found {len(form_elements)} form elements with old selector"
                )

            if not form_elements:
                # LinkedIn's newer SDUI markup uses hashed, non-semantic CSS classes,
                # so fall back to structural detection. Radio/checkbox groups (e.g. the
                # resume picker) are wrapped in a <fieldset> and must stay one section so
                # all options are visible together; every other <label> not inside such a
                # fieldset is treated as its own single-field section via its parent element
                fieldsets = await modal_content.locator("fieldset").all()
                form_elements = [await self._widen_to_question_container(fs) for fs in fieldsets]

                labels = await modal_content.locator("label").all()
                labeled_input_ids: set = set()
                for label in labels:
                    try:
                        in_fieldset = await label.locator("xpath=ancestor::fieldset").count() > 0
                    except Exception:
                        in_fieldset = False
                    if in_fieldset:
                        continue
                    label_container = label.locator("xpath=..").first
                    form_elements.append(label_container)
                    try:
                        for inp in await label_container.locator(
                            "input[type='text'], input[type='tel'], textarea"
                        ).all():
                            input_id = await inp.get_attribute("id")
                            if input_id:
                                labeled_input_ids.add(input_id)
                    except Exception:
                        pass

                # LinkedIn's newer SDUI text-question markup has no <label> at all -
                # the question text lives in a sibling <p>, associated to the <input>
                # only via aria-label/aria-describedby. Pick up any text/textarea
                # input still missed by the fieldset and label passes above.
                orphan_inputs = await modal_content.locator(
                    "input[type='text'], input[type='tel'], textarea"
                ).all()
                for inp in orphan_inputs:
                    try:
                        if await inp.locator("xpath=ancestor::fieldset").count() > 0:
                            continue
                    except Exception:
                        pass
                    input_id = await inp.get_attribute("id")
                    if input_id and input_id in labeled_input_ids:
                        continue
                    form_elements.append(await self._widen_to_text_input_container(inp))

                logger.debug(
                    f"Structural fallback: Found {len(form_elements)} form elements "
                    f"({len(fieldsets)} fieldsets)"
                )

            # Process regular form elements
            for element in form_elements:
                try:
                    await self._process_form_element(element, job, processed_file_inputs)
                except NoInfoException:
                    raise

            # Also look for upload sections separately (they may not be in fb-dash-form-element)
            upload_sections = await modal_content.locator(
                ".js-jobs-document-upload__container"
            ).all()
            logger.debug(f"Found {len(upload_sections)} upload sections")

            for upload_section in upload_sections:
                logger.debug("Processing upload section")
                await self._handle_upload_fields(upload_section, job, processed_file_inputs)

            # Additional fallback: look for any file inputs that might be missed
            file_inputs = await modal_content.locator("input[type='file']").all()
            logger.debug(f"Found {len(file_inputs)} file inputs as additional check")

            for file_input in file_inputs:
                # Check if this file input was already processed
                file_input_id = await file_input.get_attribute("id") or str(id(file_input))
                if file_input_id not in processed_file_inputs:
                    logger.debug("Processing additional file input")
                    parent_container = file_input.locator("xpath=../..").first
                    await self._handle_upload_fields(parent_container, job, processed_file_inputs)
                    processed_file_inputs.add(file_input_id)
        except NoInfoException:
            raise
        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Failed to find form elements: {tb_str}")
            await debug_capture(self.page, "fill_up_form_error")
            # Don't re-raise the exception, just log it and continue
            logger.warning("Continuing without filling form elements due to error")

    async def _process_form_element(
        self, element: Any, job: Job, processed_file_inputs: set
    ) -> None:
        """Process form element (async)"""
        logger.debug("Processing form element")
        if await self._is_resume_picker(element):
            if not await self._upload_resume_via_picker(job):
                logger.info("Falling back to selecting a saved resume")
                await self._process_form_section(element)
        elif await self._is_upload_field(element):
            await self._handle_upload_fields(element, job, processed_file_inputs)
        else:
            await self._process_form_section(element)

    async def _is_already_applied(self) -> bool:
        """Detect LinkedIn's application status panel for already-submitted jobs."""
        return await self._mark_already_applied_status()

    async def _mark_already_applied_status(self) -> bool:
        status = await self._get_already_applied_status()
        if not status:
            return False
        self.already_applied_at = status.get("applied_at")
        self.already_applied_at_text = status.get("applied_at_text")
        if self.already_applied_at_text:
            logger.info(
                f"Detected already-submitted LinkedIn application status: {self.already_applied_at_text}"
            )
        else:
            logger.info("Detected already-submitted LinkedIn application status")
        return True

    async def _get_already_applied_status(self) -> Optional[Dict[str, Optional[str]]]:
        """Return LinkedIn's application status metadata when this job was already submitted."""
        selectors = [
            "//*[normalize-space()='Application status']/following::*[normalize-space()='Application submitted'][1]",
            "//*[normalize-space()='Application submitted']",
        ]
        for selector in selectors:
            try:
                submitted_element = await find_element_safely(
                    self.page, selector, "xpath", timeout=1000
                )
                if submitted_element:
                    applied_at_text = await self._extract_already_applied_at_text(submitted_element)
                    return {
                        "applied_at": self._parse_already_applied_at(applied_at_text),
                        "applied_at_text": applied_at_text,
                    }
            except Exception as e:
                logger.debug(f"Failed checking already-applied selector {selector}: {e}")
        return None

    async def _extract_already_applied_at_text(self, submitted_element: Any) -> Optional[str]:
        """Extract the date/relative time text next to LinkedIn's submitted status."""
        selectors = [
            "xpath=following-sibling::*[1]",
            "xpath=following::*[normalize-space()][1]",
        ]
        for selector in selectors:
            try:
                date_element = submitted_element.locator(selector).first
                if await date_element.count() > 0:
                    text = (await date_element.inner_text()).strip()
                    if text and text.lower() != "view resume":
                        return text
            except Exception as e:
                logger.debug(f"Failed extracting already-applied date with {selector}: {e}")
        return None

    def _parse_already_applied_at(self, applied_at_text: Optional[str]) -> Optional[str]:
        """Convert common LinkedIn relative submitted times into an ISO timestamp."""
        if not applied_at_text:
            return None

        normalized = applied_at_text.strip().lower()
        now = datetime.now()
        if normalized in {"just now", "moments ago", "a moment ago"}:
            return now.isoformat(timespec="seconds")

        match = re.search(
            r"(?:about\s+)?(?:a|an|1|(?P<count>\d+))\s+"
            r"(?P<unit>minute|minutes|hour|hours|day|days|week|weeks|month|months|year|years)\s+ago",
            normalized,
        )
        if not match:
            return None

        count = int(match.group("count") or 1)
        unit = match.group("unit")
        if unit.startswith("minute"):
            delta = timedelta(minutes=count)
        elif unit.startswith("hour"):
            delta = timedelta(hours=count)
        elif unit.startswith("day"):
            delta = timedelta(days=count)
        elif unit.startswith("week"):
            delta = timedelta(weeks=count)
        elif unit.startswith("month"):
            delta = timedelta(days=30 * count)
        else:
            delta = timedelta(days=365 * count)
        return (now - delta).isoformat(timespec="seconds")

    async def _is_upload_field(self, element: Any) -> bool:
        """Check if element is upload field (async)"""
        # Check for file input elements
        file_inputs = await element.locator("xpath=.//input[@type='file']").all()

        # Also check for LinkedIn-specific upload containers
        upload_containers = await element.locator(".js-jobs-document-upload__container").all()
        upload_buttons = await element.locator(".jobs-document-upload__upload-button").all()

        is_upload = bool(file_inputs or upload_containers or upload_buttons)
        logger.debug(
            f"Element is upload field: {is_upload} (file_inputs: {len(file_inputs)}, containers: {len(upload_containers)}, buttons: {len(upload_buttons)})"
        )
        return is_upload

    async def _is_resume_picker(self, element: Any) -> bool:
        """Detect LinkedIn's SDUI resume picker: a radio group whose options are file names."""
        try:
            labels = await element.locator("input[type='radio']").evaluate_all(
                "els => els.map(e => e.getAttribute('aria-label') || '')"
            )
        except Exception as e:
            logger.debug(f"Failed checking for resume picker: {e}")
            return False
        is_picker = bool(labels) and all(
            re.search(r"\.(pdf|docx?)$", label.strip(), re.IGNORECASE) for label in labels
        )
        logger.debug(f"Element is resume picker: {is_picker} ({len(labels)} radio options)")
        return is_picker

    async def _upload_resume_via_picker(self, job: Job) -> bool:
        """Upload the resume through the SDUI picker's upload control. Returns False on failure."""
        scope = self.page.locator('[data-testid="dialog-content"]').first
        if await scope.count() == 0:
            scope = self.page
        candidates = [
            scope.get_by_role("button", name=re.compile(r"upload", re.IGNORECASE)),
            scope.get_by_text(re.compile(r"^\s*upload", re.IGNORECASE)),
        ]
        trigger = None
        for candidate in candidates:
            if await candidate.count() > 0:
                trigger = candidate.first
                break
        if trigger is None:
            logger.warning(f"Resume picker upload control not found for job: {job.url}")
            await debug_capture(self.page, "resume_picker_upload_not_found")
            return False

        logger.info("Uploading resume via resume picker")
        try:
            await self._create_and_upload_resume(_FileChooserUpload(self.page, trigger), job)
        except Exception as e:
            logger.warning(f"Failed to upload resume via resume picker for job {job.url}: {e}")
            return False
        return True

    async def _handle_upload_fields(
        self, element: Any, job: Job, processed_file_inputs: set
    ) -> None:
        """Handle file upload fields (async)"""
        logger.info("Handling upload fields")

        try:
            show_more_button = await find_element_safely(
                self.page,
                "//button[contains(@aria-label, 'Show more resumes')]",
                "xpath",
            )
            if show_more_button:
                await show_more_button.click(timeout=1000)
                logger.debug("Clicked 'Show more resumes' button")
        except Exception:
            logger.debug("'Show more resumes' button not found, continuing...")

        # First try to find file inputs within the specific element
        file_upload_elements = await element.locator("xpath=.//input[@type='file']").all()

        # If no file inputs found in the element, fall back to global search
        if not file_upload_elements:
            logger.debug("No file inputs found in element, searching globally")
            file_upload_elements = await self.page.locator("xpath=//input[@type='file']").all()

        logger.debug(f"Found {len(file_upload_elements)} file upload elements")

        for upload_element in file_upload_elements:
            try:
                # Check if this file input was already processed
                file_input_id = await upload_element.get_attribute("id") or str(id(upload_element))
                if file_input_id in processed_file_inputs:
                    logger.debug(f"File input {file_input_id} already processed, skipping")
                    continue

                # Get the parent container to determine what type of upload this is
                parent = upload_element.locator("xpath=..").first
                container_text = (await parent.text_content() or "").lower()

                # Also check the label text if available
                # try:
                #     input_id = await upload_element.get_attribute("id") or ""
                #     if input_id:
                #         label_text = (
                #             await self.page.locator(
                #                 f"xpath=//label[@for='{input_id}']"
                #             ).first.text_content()
                #             or ""
                #         ).lower()
                #         container_text += " " + label_text
                # except Exception:
                #     pass

                # Make the hidden input visible for uploading
                try:
                    await upload_element.evaluate("el => el.classList.remove('hidden')")
                except Exception:
                    pass

                logger.debug(f"Processing upload field with context: {container_text}")

                # Mark this file input as processed before generating files
                processed_file_inputs.add(file_input_id)

                accept_types = (await upload_element.get_attribute("accept") or "").lower()

                # output = self.gpt_answerer.resume_or_cover(container_text)
                if "image/" in accept_types or "photo" in container_text:
                    logger.info("Uploading photo")
                    await self._create_and_upload_photo(upload_element, job)
                elif "resume" in container_text:
                    logger.info("Uploading resume")
                    if (
                        self.resume_generator_manager is not None
                        and getattr(self.resume_generator_manager, "selected_style", None)
                        is not None
                    ):
                        await self._create_and_upload_resume(upload_element, job)
                    elif self.ready_made_resume_path is not None:
                        logger.info(
                            "Resume generator is not ready; falling back to ready-made resume"
                        )
                        await self._create_and_upload_resume(upload_element, job)
                    else:
                        raise NoInfoException(
                            "No resume generator style selected and no ready-made resume configured"
                        )
                elif "cover" in container_text:
                    logger.info("Uploading cover letter")
                    await self._create_and_upload_cover_letter(upload_element, job)

            except Exception as e:
                logger.warning(f"Failed to process upload element: {e}")
                await debug_capture(self.page, "upload_element_error")
                continue

        logger.debug("Finished handling upload fields")

    async def _create_and_upload_photo(self, element: Any, job: Job) -> None:
        """Upload a configured profile photo or fall back to the visible LinkedIn avatar."""
        allowed_extensions = {".jpg", ".jpeg", ".png", ".gif"}
        max_file_size = 2 * 1024 * 1024

        if self.ready_made_photo_path is not None:
            photo_path = self.ready_made_photo_path.resolve()
            if photo_path.suffix.lower() not in allowed_extensions:
                raise ValueError(
                    "Photo file format is not allowed. Only JPG, JPEG, PNG, and GIF formats are supported."
                )
            if photo_path.stat().st_size > max_file_size:
                raise ValueError("Photo file size exceeds the maximum limit of 2 MB.")

            abs_path = os.path.abspath(str(photo_path))
            await element.set_input_files(abs_path)
            await async_pause(1, 2)
            logger.info(f"Photo uploaded from path: {photo_path}")
            return

        os.makedirs(self.generated_photo_dir, exist_ok=True)

        image_selectors = [
            ".jobs-easy-apply-modal .artdeco-entity-lockup__image--type-circle img",
            ".jobs-easy-apply-modal img[src*='profile-displayphoto']",
            ".jobs-easy-apply-modal img[title][src]",
        ]

        image_src = ""
        for selector in image_selectors:
            image = await find_element_safely(self.page, selector, "css selector")
            if not image:
                continue
            image_src = (await image.get_attribute("src") or "").strip()
            if image_src:
                break

        if not image_src:
            raise ValueError("Could not locate a profile photo source for the upload field")

        data_url = await self.page.evaluate(
            """async (src) => {
                const response = await fetch(src, { credentials: 'include' });
                if (!response.ok) {
                    throw new Error(`Photo fetch failed with status ${response.status}`);
                }
                const blob = await response.blob();
                return await new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result);
                    reader.onerror = () => reject(reader.error || new Error('Photo read failed'));
                    reader.readAsDataURL(blob);
                });
            }""",
            image_src,
        )

        if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
            raise ValueError("Profile photo fetch did not return an image data URL")

        header, encoded = data_url.split(",", 1)
        mime_type = header.split(";", 1)[0].split(":", 1)[1].lower()
        extension_map = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
        }
        extension = extension_map.get(mime_type)
        if extension is None:
            raise ValueError(f"Unsupported photo MIME type for upload: {mime_type}")

        file_path = (
            self.generated_photo_dir / f"PHOTO_{job.company_name}_{job.job_title}{extension}"
        )
        file_bytes = base64.b64decode(encoded)
        if len(file_bytes) > max_file_size:
            raise ValueError("Profile photo exceeds LinkedIn 2 MB upload limit")

        with open(file_path, "wb") as file_handle:
            file_handle.write(file_bytes)

        await element.set_input_files(os.path.abspath(str(file_path)))
        await async_pause(1, 2)
        logger.info(f"Photo uploaded from generated path: {file_path}")

    async def _detect_already_selected_resume(self, parent: Any) -> bool:
        """Detect if the is already selected resume in Easy Apply form"""
        already_selected = False
        try:
            sel = ".jobs-document-upload-redesign-card__toggle-label"
            texts = await parent.locator(sel).evaluate_all(
                "els => els.map(e => e.textContent || '')"
            )
            if not texts:
                texts = await self.page.locator(sel).evaluate_all(
                    "els => els.map(e => e.textContent || '')"
                )
            for lbl_text in texts:
                lbl_text = lbl_text.strip()
                st = sanitize_text(lbl_text)
                if st.startswith("deselect") and st.endswith(".pdf"):
                    already_selected = True
                    logger.info(
                        f"Resume already selected via toggle label, skipping upload: {lbl_text}"
                    )
                    break
        except Exception:
            pass
        if already_selected:
            return True
        return False

    async def _create_and_upload_cover_letter(self, element: Any, job: Job) -> None:
        logger.info("Starting the process of creating and uploading cover letter.")

        cover_letter_text = self.gpt_answerer.write_cover_letter()
        cover_letter_text = self.resume_anonymizer.deanonymize_text(cover_letter_text)

        try:
            if not os.path.exists(self.generated_cover_letter_dir):
                logger.debug(f"Creating directory at path: {self.generated_cover_letter_dir}")
            os.makedirs(self.generated_cover_letter_dir, exist_ok=True)
        except Exception as e:
            logger.error(
                f"Failed to create directory: {self.generated_cover_letter_dir}. Error: {e}"
            )
            raise

        while True:
            try:
                file_path_pdf = os.path.join(
                    self.generated_cover_letter_dir,
                    f"Cover_Letter_{job.company_name}_{job.job_title}.pdf",
                )
                logger.debug(f"Generated file path for cover letter: {file_path_pdf}")

                c = canvas.Canvas(file_path_pdf, pagesize=A4)
                page_width, page_height = A4
                text_object = c.beginText(50, page_height - 50)
                text_object.setFont("Helvetica", 12)

                max_width = page_width - 100
                bottom_margin = 50

                def split_text_by_width(text, font, font_size, max_width):
                    wrapped_lines = []
                    for line in text.splitlines():
                        if stringWidth(line, font, font_size) > max_width:
                            words = line.split()
                            new_line = ""
                            for word in words:
                                if stringWidth(new_line + word + " ", font, font_size) <= max_width:
                                    new_line += word + " "
                                else:
                                    wrapped_lines.append(new_line.strip())
                                    new_line = word + " "
                            wrapped_lines.append(new_line.strip())
                        else:
                            wrapped_lines.append(line)
                    return wrapped_lines

                lines = split_text_by_width(cover_letter_text, "Helvetica", 12, max_width)

                for line in lines:
                    text_height = text_object.getY()
                    if text_height > bottom_margin:
                        text_object.textLine(line)
                    else:
                        c.drawText(text_object)
                        c.showPage()
                        text_object = c.beginText(50, page_height - 50)
                        text_object.setFont("Helvetica", 12)
                        text_object.textLine(line)

                c.drawText(text_object)
                c.save()
                logger.info(f"Cover letter successfully generated and saved to: {file_path_pdf}")

                break
            except Exception as e:
                logger.error(f"Failed to generate cover letter: {e}")
                tb_str = traceback.format_exc()
                logger.error(f"Traceback: {tb_str}")
                raise

        file_size = os.path.getsize(file_path_pdf)
        max_file_size = 2 * 1024 * 1024  # 2 MB
        logger.debug(f"Cover letter file size: {file_size} bytes")
        if file_size > max_file_size:
            logger.error(f"Cover letter file size exceeds 2 MB: {file_size} bytes")
            raise ValueError("Cover letter file size exceeds the maximum limit of 2 MB.")

        allowed_extensions = {".pdf", ".doc", ".docx"}
        file_extension = os.path.splitext(file_path_pdf)[1].lower()
        logger.debug(f"Cover letter file extension: {file_extension}")
        if file_extension not in allowed_extensions:
            logger.error(f"Invalid cover letter file format: {file_extension}")
            raise ValueError(
                "Cover letter file format is not allowed. Only PDF, DOC, and DOCX formats are supported."
            )

        try:
            logger.info(f"Uploading cover letter from path: {file_path_pdf}")
            await element.set_input_files(os.path.abspath(file_path_pdf))
            await async_pause(1, 2)
            logger.info(f"Cover letter created and uploaded successfully: {file_path_pdf}")
        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Cover letter upload failed: {tb_str}")
            await debug_capture(self.page, "cover_letter_upload_error")
            raise Exception(f"Upload failed: \nTraceback:\n{tb_str}")

    async def _handle_terms_of_service(self, element: Any) -> bool:
        """Handle terms of service checkbox (async)"""
        try:
            # Check if element is checkbox to prevent false ToS processing on non-checkbox elements
            checkboxes = await element.locator("input[type='checkbox']").all()
            if not checkboxes:
                return False
            checkbox_text = (
                await element.locator("xpath=.//label").first.text_content() or ""
            ).lower()
        except Exception:
            return False
        if checkbox_text:
            if any(
                term in checkbox_text
                for term in [
                    "terms of service",
                    "privacy policy",
                    "terms of use",
                    "confirm",
                    "agree",
                    "accept",
                ]
            ):
                label_el = element.locator("xpath=.//label").first
                await label_el.click(timeout=1000)
                logger.debug("Clicked terms of service checkbox/radio")
                return True
        return False

    async def _find_and_handle_checkbox_question(self, section: Any) -> bool:
        """Handle checkbox questions that are not terms of service (async)"""
        logger.debug("Searching for checkbox questions in the section.")

        # Look for checkboxes in the new LinkedIn form structure
        checkboxes = {}

        # Try different selectors for checkboxes
        checkbox_selectors = [
            "input[type='checkbox']",
            ".fb-form-element__checkbox",
            # "[data-test-text-selectable-option__input]",
            "[data-test-checkbox-form-component] input[type='checkbox']",
        ]

        for selector in checkbox_selectors:
            found_checkboxes = await find_elements_safely(section, selector, "css selector")
            for checkbox in found_checkboxes:
                checkbox_id = await checkbox.get_attribute("id")
                if checkbox_id and checkbox_id not in checkboxes:
                    checkboxes[checkbox_id] = checkbox

        checkboxes = list(checkboxes.values())

        if checkboxes:
            logger.debug(f"Found {len(checkboxes)} checkboxes")

            # Extract question text from the section
            question_text = ""
            try:
                # Look for question text in various places
                question_selectors = [
                    "legend",
                    ".fb-dash-form-element__label",
                    "[data-test-checkbox-form-title]",
                    ".jobs-easy-apply-form-section__group-title",
                    # New LinkedIn SDUI markup has no legend/title element; the question
                    # text is a plain <p> preceding the <fieldset> in the widened section,
                    # so it's always the first <p> in document order.
                    "p",
                ]

                for selector in question_selectors:
                    question_element = await find_element_safely(section, selector, "css selector")
                    if question_element:
                        question_text = (await question_element.text_content() or "").strip()
                        # Clean up the question text
                        question_text = self._deduplicate_question_text(question_text)
                        question_list = []
                        for question in question_text.split("\n"):
                            question_text = self._deduplicate_question_text(question.strip())
                            if question_text:
                                question_list.append(question_text)
                        question_text = "\n".join(question_list)
                        if question_text and "required" not in question_text.lower():
                            break

                # If no question found, try to get it from the section text
                if not question_text:
                    section_text = (await section.text_content() or "").strip()
                    # Extract meaningful text, removing checkbox labels
                    lines = section_text.split("\n")
                    for line in lines:
                        line = line.strip()
                        if line and not any(
                            opt in line.lower()
                            for opt in ["confirmed", "agree", "accept", "required"]
                        ):
                            question_text = line
                            break

                logger.debug(f"Extracted question text: '{question_text}'")
                self.previous_question_texts.append(question_text)

            except Exception as e:
                logger.warning(f"Failed to extract question text: {e}")
                question_text = ""

            # Extract checkbox options
            checkbox_options = []
            checkbox_data = []  # Store (checkbox, label_text) pairs

            for checkbox in checkboxes:
                try:
                    # Get the associated label
                    checkbox_id = await checkbox.get_attribute("id")
                    label_text = ""

                    if checkbox_id:
                        # Look for label with matching 'for' attribute
                        label = section.locator(f"label[for='{checkbox_id}']").first
                        if label:
                            label_text = (await label.text_content() or "").strip()

                    # If no label found, try to get text from parent elements
                    if not label_text:
                        # Look for text in the same container as the checkbox
                        parent = checkbox.locator("xpath=..").first
                        if parent:
                            parent_text = (await parent.text_content() or "").strip()
                            # Extract text that's not the question
                            if parent_text and parent_text != question_text:
                                label_text = parent_text

                    if not label_text:
                        # New LinkedIn SDUI markup renders an empty <label> as a click
                        # target; the visible option text instead lives on a sibling <p>
                        # under the ancestor role="checkbox" wrapper
                        role_ancestor = checkbox.locator(
                            "xpath=ancestor::*[@role='checkbox'][1]"
                        ).first
                        if await role_ancestor.count() > 0:
                            role_text = (await role_ancestor.text_content() or "").strip()
                            if role_text and role_text != question_text:
                                label_text = role_text

                    if not label_text:
                        # Option text is a <p> sibling of the checkbox's wrapper, with no
                        # aria-label or role="checkbox" ancestor to read it from
                        label_text = await checkbox.evaluate(_OPTION_TEXT_JS)

                    if label_text:
                        checkbox_options.append(label_text)
                        checkbox_data.append((checkbox, label_text))
                        logger.debug(f"Checkbox option: '{label_text}'")

                except Exception as e:
                    logger.warning(f"Failed to extract checkbox option: {e}")
                    continue

            if not checkbox_options:
                logger.debug("No checkbox options found, skipping")
                return False

            # Use LLM to select which checkboxes to check
            try:
                logger.info(f"Asking LLM to select checkboxes for question: {question_text}")
                logger.info(f"Available options: {checkbox_options}")

                # Look for existing answer if it's not a cover letter field
                existing_answer = None
                current_question_sanitized = sanitize_text(question_text)
                for item in self.all_questions:
                    if (
                        item.question == current_question_sanitized
                        and item.question_type == "checkbox"
                    ):
                        existing_answer = item.answer
                        logger.debug(f"Found existing answer: {existing_answer}")
                        break

                if existing_answer:
                    selected_options = existing_answer
                else:
                    selected_options = self.gpt_answerer.select_many_answers_from_options(
                        question_text, checkbox_options, self.previous_question_texts[:-1]
                    )
                    if not any(self._is_no_info_answer(s) for s in selected_options):
                        self._save_questions(
                            Question(
                                question_type="checkbox",
                                question=question_text,
                                answer=selected_options,
                            )
                        )

                logger.info(f"LLM selected options: {selected_options}")

                # Check the selected checkboxes
                for checkbox, label_text in checkbox_data:
                    try:
                        # Check if this option was selected by LLM
                        if any(
                            selected in label_text.lower() or label_text.lower() in selected.lower()
                            for selected in selected_options
                            if not self._is_no_info_answer(selected)
                        ):
                            if not await checkbox.is_checked():
                                logger.info(f"Checking checkbox: {label_text}")
                                await self._click_checkbox_safely(checkbox, section)
                                logger.debug(f"Clicked checkbox: {label_text}")
                            else:
                                logger.debug(f"Checkbox already checked: {label_text}")
                        else:
                            logger.debug(f"Checkbox not selected by LLM: {label_text}")

                    except Exception as e:
                        logger.warning(f"Failed to process checkbox '{label_text}': {e}")
                        continue

                return True

            except Exception as e:
                logger.error(f"Failed to use LLM for checkbox selection: {e}")
                # Fallback: check confirmation checkboxes only
                for checkbox, label_text in checkbox_data:
                    try:
                        if any(
                            confirm_word in label_text.lower()
                            for confirm_word in ["confirmed", "confirm", "agree", "accept"]
                        ):
                            if not await checkbox.is_checked():
                                logger.info(
                                    f"Fallback: Checking confirmation checkbox: {label_text}"
                                )
                                await self._click_checkbox_safely(checkbox, section)
                                logger.debug(f"Clicked confirmation checkbox: {label_text}")
                    except Exception as e:
                        logger.warning(f"Failed to process fallback checkbox '{label_text}': {e}")
                        continue

                return True

        return False

    async def _click_checkbox_safely(self, checkbox: Any, section: Any) -> None:
        """Safely click a checkbox by trying the label first, then the checkbox itself (async)"""
        try:
            # First try to click the associated label
            checkbox_id = await checkbox.get_attribute("id")
            if checkbox_id:
                label = section.locator(f"label[for='{checkbox_id}']").first
                if label:
                    logger.debug("Clicking checkbox via label")
                    await label.click(timeout=1000)
                    return

            # If no label found or label click failed, try clicking the checkbox directly
            logger.debug("Clicking checkbox directly")
            await checkbox.click(timeout=1000)

        except Exception as e:
            logger.warning(f"Failed to click checkbox safely: {e}")
            # New LinkedIn SDUI markup draws the visible, clickable checkbox on the
            # ancestor role="checkbox" wrapper; the native <input>/<label> are visually
            # hidden and fail Playwright's actionability check, so try that next.
            try:
                role_ancestor = checkbox.locator("xpath=ancestor::*[@role='checkbox'][1]").first
                if await role_ancestor.count() > 0:
                    logger.debug("Clicking checkbox via role='checkbox' ancestor")
                    await role_ancestor.click(timeout=1000)
                    return
            except Exception as e2:
                logger.warning(f"Failed to click checkbox via role ancestor: {e2}")

            # Final fallback: try clicking the checkbox directly
            try:
                await checkbox.click(timeout=1000)
            except Exception as e3:
                logger.error(f"All checkbox click attempts failed: {e3}")
                await debug_capture(self.page, "checkbox_click_error")

    async def _is_resume_picker_radiogroup(self, section: Any) -> bool:
        """Detect LinkedIn's "select a resume" radiogroup among generic radio questions.

        It lists every previously uploaded resume (filename + upload date) as a radio
        option with one already checked, so its option labels are just resume filenames
        rather than an answerable question. Concatenating all of them as question text
        (potentially years of history) produces garbage that can't be answered by cache
        or LLM, so this must be detected and skipped before that text is ever built.
        """
        try:
            radiogroup = section.locator("[role='radiogroup']").first
            if await radiogroup.count() == 0:
                return False
            labels = await radiogroup.locator("[role='radio'][aria-label]").evaluate_all(
                "els => els.map(e => (e.getAttribute('aria-label') || '').toLowerCase())"
            )
        except Exception:
            return False
        resume_extensions = (".pdf", ".doc", ".docx")
        return bool(labels) and all(label.endswith(resume_extensions) for label in labels)

    async def _find_and_handle_radio_question(self, section: Any) -> bool:
        """Handle radio button questions (async)"""
        # Look for radio buttons in the new LinkedIn form structure
        logger.debug("Searching for radio buttons in the section.")
        radios = {}

        # Try different selectors for radio buttons
        radio_selectors = [
            ".fb-text-selectable__option",
            "input[type='radio']",
            ".artdeco-button--toggle",
            "[role='radio']",
        ]

        for selector in radio_selectors:
            loc = section.locator(selector)
            ids = await loc.evaluate_all("els => els.map(e => e.id || '')")
            found_radios = await loc.all()
            for radio, radio_id in zip(found_radios, ids):
                if radio_id and radio_id not in radios:
                    radios[radio_id] = radio

        # Remove duplicates
        radios = list(radios.values())

        if radios:
            if await self._is_resume_picker_radiogroup(section):
                logger.info(
                    "Detected resume-selection radio group; keeping LinkedIn's default "
                    "selected resume"
                )
                return True

            # Try to find the question text
            try:
                question_text = (await section.text_content() or "").lower().strip()
                question_list = []
                for question in question_text.split("\n"):
                    question_text = self._deduplicate_question_text(question.strip())
                    if question_text:
                        question_list.append(question_text)
                question_text = "\n".join(question_list)
                question_text = self._deduplicate_question_text(question_text)
                self.previous_question_texts.append(question_text)
            except Exception:
                question_text = ""

            # Extract options text from radio buttons and their labels
            options = await section.locator(",".join(radio_selectors)).evaluate_all(
                "els => { const optionText = "
                + _OPTION_TEXT_JS
                + """;
                    const seen = new Set();
                    return els.reduce((acc, e) => {
                        if (e.id && !seen.has(e.id)) {
                            seen.add(e.id);
                            const text = optionText(e);
                            if (text) acc.push(text);
                        }
                        return acc;
                    }, []);
                }"""
            )
            options = list(dict.fromkeys(options))

            if not options:
                logger.debug("No options extracted from radio buttons, skipping")
                return False

            cached_question = self._find_cached_question(question_text, "radio")
            if cached_question:
                await self._select_radio(section, radios, cached_question.answer)
                logger.debug("Selected existing radio answer")
                return True

            logger.info(f"Asking question: {question_text}")
            logger.info(f"Available options: {options}")
            answer = self.gpt_answerer.select_one_answer_from_options(
                question_text, options, self.previous_question_texts[:-1]
            )
            if self._is_no_info_answer(answer):
                raise NoInfoException(f"No info found for question: {question_text}")
            question_data = Question(question_type="radio", question=question_text, answer=answer)
            self._save_questions(question_data)
            self.all_questions = self._load_questions()
            await self._select_radio(section, radios, answer)
            logger.debug("Selected new radio answer")
            return True
        return False

    async def _find_and_handle_textbox_question(self, section: Any) -> bool:
        """Handle textbox questions (async)"""
        logger.debug("Searching for text fields in the section.")

        # Look for text input fields in the new LinkedIn form structure
        text_field = None

        # Try different selectors for text inputs
        selectors = [
            "input[type='text']",
            "input[type='tel']",
            "textarea",
            ".artdeco-text-input--input",
        ]

        for selector in selectors:
            fields = await find_elements_safely(section, selector, "css selector")
            if fields:
                text_field = fields[0]
                break

        if text_field:
            # Try to find the label for this field
            try:
                # Look for label in various ways
                label = None
                label_selectors = [
                    "label",
                    ".fb-dash-form-element__label",
                    ".artdeco-text-input--label",
                    ".jobs-easy-apply-form-section__group-title",
                ]

                for label_selector in label_selectors:
                    label = await find_element_safely(section, label_selector, "css selector")
                    if label:
                        break

                if label:
                    question_text = (await label.text_content() or "").lower().strip()
                    question_text = self._deduplicate_question_text(question_text)
                else:
                    question_text = ""

                # Add placeholder to question text if it exists
                placeholder_text = await text_field.get_attribute(
                    "placeholder"
                ) or await text_field.get_attribute("aria-label")
                if placeholder_text:
                    placeholder_text = placeholder_text.lower().strip()
                    placeholder_text = self._deduplicate_question_text(placeholder_text)
                    question_text += f"\n{placeholder_text}"

                self.previous_question_texts.append(question_text)
                logger.debug(f"Found text field with label: {question_text}")
            except Exception as e:
                logger.warning(f"Could not find label for text field: {e}")
                question_text = ""

            is_numeric = await self._is_numeric_field(text_field, question_text)
            logger.info(f"Is the field numeric? {'Yes' if is_numeric else 'No'}")

            question_type = "numeric" if is_numeric else "textbox"

            # Check if it's a cover letter field (case-insensitive)
            is_cover_letter = "cover letter" in question_text.lower()
            logger.info(f"question: {question_text}")
            # Look for existing answer if it's not a cover letter field
            existing_answer = None
            if not is_cover_letter:
                cached_question = self._find_cached_question(question_text, question_type)
                if cached_question:
                    cached_answer = cached_question.answer.strip()
                    if self._is_no_info_answer(cached_answer):
                        logger.info(f"Ignoring cached No info answer for question: {question_text}")
                    else:
                        existing_answer = cached_answer
                        logger.debug(
                            "Found existing answer for '%s' via cached %s field",
                            question_text,
                            cached_question.question_type,
                        )

            if existing_answer and not is_cover_letter:
                answer = existing_answer
                logger.info(f"Using existing answer: {answer}")
            elif is_cover_letter:
                logger.info(f"Cover letter field found: {question_text}")
                cover_letter_text = self.gpt_answerer.write_cover_letter()
                answer = cover_letter_text
            else:
                if is_numeric:
                    logger.info(f"Answering numeric question: {question_text}")
                    answer = self.gpt_answerer.answer_question_numeric(
                        question_text, self.previous_question_texts[:-1]
                    )
                else:
                    logger.info(f"Answering textual question: {question_text}")
                    answer = self.gpt_answerer.answer_question_textual_wide_range(
                        question_text, self.previous_question_texts[:-1]
                    )

            if self._is_no_info_answer(answer):
                if not await self._is_required_text_field(section, text_field):
                    logger.info(
                        f"Skipping optional text field with no available answer: {question_text}"
                    )
                    return True
                raise NoInfoException(f"No info found for question: {question_text}")

            answer = self.resume_anonymizer.deanonymize_text(answer)
            await text_field.fill(answer)
            logger.debug("Entered answer into the textbox.")

            await self._process_autocomplete_suggestions(text_field)

            # Save non-cover letter answers
            if not is_cover_letter and not existing_answer:
                question_data = Question(
                    question_type=question_type, question=question_text, answer=answer
                )
                self._save_questions(question_data)
                logger.debug("Saved non-cover letter answer.")

            return True

        logger.debug("No text fields found in the section.")
        return False

    async def _is_required_text_field(self, section: Any, text_field: Any) -> bool:
        """Best-effort detection for LinkedIn required text fields."""
        for attr in ("required", "aria-required"):
            try:
                value = await text_field.get_attribute(attr)
                if value is not None and str(value).lower() in {"", "true", "required"}:
                    return True
            except Exception:
                pass

        try:
            labels = await section.locator("label").all()
            for label in labels:
                label_text = (await label.text_content() or "").strip().lower()
                if "optional" in label_text:
                    continue
                if "*" in label_text:
                    return True
        except Exception as e:
            logger.debug(f"Failed checking required text field labels: {e}")

        return False

    async def _process_autocomplete_suggestions(self, text_field: Any) -> None:
        """Handle autocomplete suggestions if they appear (async)"""
        await async_pause(1, 2)
        try:
            # Check if autocomplete suggestions are visible
            suggestions = self.page.locator(".basic-typeahead__selectable")
            if await suggestions.count() > 0:
                logger.debug("Autocomplete suggestions detected, selecting first option")
                try:
                    await self.page.keyboard.press("ArrowDown")
                    await async_pause()
                    await self.page.keyboard.press("Enter")
                except Exception:
                    pass
                logger.debug("Selected first suggestion from autocomplete")
        except Exception as e:
            logger.debug(f"No autocomplete suggestions found or error handling suggestions: {e}")

    async def _find_and_handle_dropdown_question(self, section: Any) -> bool:
        """Handle dropdown questions (async)"""
        try:
            # Look for dropdowns in the new LinkedIn form structure
            dropdowns = {}

            # Try different selectors for dropdowns
            dropdown_selectors = [
                "select",
                "[data-test-text-entity-list-form-select]",
                ".fb-dash-form-element__select-dropdown",
                "select.fb-dash-form-element__select-dropdown",
            ]

            for selector in dropdown_selectors:
                _selector = f"css={selector}" if selector == "select" else selector
                found_dropdowns = await find_elements_safely(section, _selector, "css selector")
                for dropdown in found_dropdowns:
                    dropdown_id = await dropdown.get_attribute("id")
                    if dropdown_id and dropdown_id not in dropdowns:
                        dropdowns[dropdown_id] = dropdown

            # Remove duplicates
            dropdowns = list(dropdowns.values())

            if dropdowns:
                logger.info("Dropdowns found")
                dropdown = dropdowns[0]
                # Try to gather options text if possible
                options = []
                try:
                    # For native select elements, get options via DOM
                    options = [
                        t
                        for t in await dropdown.locator("option").evaluate_all(
                            "els => els.map(e => e.textContent?.trim() ?? '')"
                        )
                        if t
                    ]
                except Exception:
                    options = []

                # Try to find the label for this dropdown
                try:
                    label_selectors = [
                        "label",
                        ".fb-dash-form-element__label",
                        "[data-test-text-entity-list-form-title]",
                    ]

                    question_text = ""
                    for label_selector in label_selectors:
                        # An empty <label> must not end the search - keep going until a
                        # selector yields actual question text
                        labels = await find_elements_safely(section, label_selector, "css selector")
                        for label in labels:
                            label_text = (await label.text_content() or "").lower().strip()
                            if label_text:
                                question_text = self._deduplicate_question_text(label_text)
                                break
                        if question_text:
                            break

                    if not question_text:
                        question_text = await self._extract_accessible_name(dropdown)

                    if question_text:
                        self.previous_question_texts.append(question_text)
                    else:
                        logger.warning(
                            "Dropdown has no question text; answering from options "
                            f"alone: {options}"
                        )
                        await debug_capture(self.page, "dropdown_without_label")
                except Exception as e:
                    logger.warning(f"Could not find label for dropdown: {e}")
                    question_text = ""

                try:
                    selection_info = await dropdown.evaluate(
                        """el => {
                            const opt = el.options[el.selectedIndex];
                            if (!opt) return null;
                            return {
                                text: (opt.textContent || '').trim(),
                                index: el.selectedIndex,
                                hasSelectedAttr: opt.hasAttribute('selected'),
                            };
                        }"""
                    )
                    if selection_info and (
                        selection_info["index"] > 0 or selection_info["hasSelectedAttr"]
                    ):
                        current_selection = selection_info["text"]
                    else:
                        current_selection = ""
                except Exception:
                    current_selection = ""
                logger.debug(f"Current selection: {current_selection}")

                if self._is_meaningful_existing_answer(current_selection):
                    logger.info(
                        f"Dropdown question '{question_text}' already has a selected answer: {current_selection}"
                    )
                    self._save_questions(
                        Question(
                            question_type="dropdown",
                            question=question_text,
                            answer=current_selection,
                        )
                    )
                    return True

                existing_answer = None
                cached_question = self._find_cached_question(question_text, "dropdown")
                if cached_question:
                    existing_answer = (
                        cached_question.answer.strip()
                        if isinstance(cached_question.answer, str)
                        else cached_question.answer
                    )

                if existing_answer:
                    logger.debug(
                        f"Found existing answer for question '{question_text}': {existing_answer}"
                    )
                    if current_selection != existing_answer:
                        logger.debug(f"Updating selection to: {existing_answer}")
                        if not await self._select_dropdown_option(dropdown, existing_answer):
                            logger.warning(
                                f"Could not select cached answer '{existing_answer}' for "
                                f"dropdown question '{question_text}'"
                            )
                            return False
                else:
                    logger.info(f"Asking question: {question_text}")
                    logger.info(f"Available options: {options}")
                    answer = self.gpt_answerer.select_one_answer_from_options(
                        question_text, options, self.previous_question_texts[:-1]
                    )
                    if self._is_no_info_answer(answer):
                        raise NoInfoException(f"No info found for question: {question_text}")
                    question_data = Question(
                        question_type="dropdown", question=question_text, answer=answer
                    )
                    self._save_questions(question_data)
                    if not await self._select_dropdown_option(dropdown, answer):
                        logger.warning(
                            f"Could not select answer '{answer}' for dropdown question "
                            f"'{question_text}'"
                        )
                        return False
                    logger.debug(f"Selected new dropdown answer: {answer}")

                return True

            else:
                logger.debug("No dropdown found. Logging elements for debugging.")
                try:
                    elements_count = await section.locator("xpath=.//*").count()
                    logger.debug(f"Elements found count: {elements_count}")
                except Exception:
                    pass
                return False

        except NoInfoException:
            raise
        except Exception as e:
            logger.warning(f"Failed to handle dropdown or combobox question: {e}", exc_info=True)
            await debug_capture(self.page, "dropdown_question_error")
            return False

    _NUMERIC_QUESTION_KEYWORDS = (
        "salary",
        "compensation",
        "pay",
        "wage",
        "rate",
        "earnings",
        "years of experience",
        "how many years",
        "how many months",
        "number of",
        "how many",
        "gpa",
        "grade point",
    )

    async def _is_numeric_field(self, field: Any, question_text: str = "") -> bool:
        """Check if field is numeric (async)"""
        field_type = (await field.get_attribute("type") or "").lower()
        field_id = (await field.get_attribute("id") or "").lower()
        is_numeric = (
            "numeric" in field_id
            or field_type == "number"
            or ("text" == field_type and "numeric" in field_id)
        )
        if not is_numeric:
            q = question_text.lower()
            is_numeric = any(
                re.search(r"\b" + re.escape(kw) + r"\b", q)
                for kw in self._NUMERIC_QUESTION_KEYWORDS
            )
        logger.debug(f"Field type: {field_type}, Field ID: {field_id}, Is numeric: {is_numeric}")
        return is_numeric

    def _is_meaningful_existing_answer(self, value: str | None) -> bool:
        if not value:
            return False
        normalized = sanitize_text(value)
        if not normalized:
            return False
        placeholders = {
            "select an option",
            "choose an option",
            "select",
            "choose",
            "please select",
            "empty response",
            "no info",
        }
        return normalized not in placeholders

    def _deduplicate_question_text(self, question_text: str) -> str:
        """If the question consists of two lines, and the second line is the same as the first line, use the first line"""
        if len(question_text) % 2 == 0:
            half_length = len(question_text) // 2
            if question_text[:half_length] == question_text[half_length:]:
                question_text = question_text[:half_length]
                return question_text
        question_list = question_text.split("\n")
        deduplicated_question_list = list(dict.fromkeys(question_list))
        question_text = "\n".join(deduplicated_question_list)
        return question_text

    async def _select_radio(self, section: Any, radios: List[Any], answer: str) -> None:
        """Select radio button based on answer (async)"""
        logger.debug(f"Selecting radio option: {answer}")
        for radio in radios:
            try:
                # Extract text from radio button or its associated label
                radio_text = ""

                # Look for label with matching 'for' attribute
                radio_id = await radio.get_attribute("id")
                if radio_id:
                    label = section.locator(f"label[for='{radio_id}']").first
                    radio_text = await radio.evaluate(_OPTION_TEXT_JS)

                logger.debug(f"Radio button text extracted: '{radio_text}'")

                if radio_text and (answer.lower() in radio_text or radio_text in answer.lower()):
                    # Try different ways to click the radio button
                    try:
                        # First try clicking the associated label (most reliable for LinkedIn)
                        if radio_id:
                            await label.click(timeout=1000)
                            logger.debug(f"Clicked radio label: {radio_text}")
                            return
                    except Exception:
                        logger.warning(f"Failed to click radio button: {radio_text}")

            except Exception as e:
                logger.warning(f"Failed to process radio button: {e}")
                continue

        # If no match found, click the first radio button as fallback
        try:
            await radios[0].click(timeout=1000)
            logger.debug("Clicked first radio button as fallback")
        except Exception:
            logger.warning("Failed to click any radio button")

    async def _extract_accessible_name(self, element: Any) -> str:
        """Derive a field's question text from its accessible name (async).

        LinkedIn's SDUI markup sometimes renders an empty <label>, leaving the
        question text reachable only via aria-label/aria-labelledby.
        """
        try:
            text = await element.evaluate(
                """el => {
                    const direct = (el.getAttribute('aria-label') || '').trim();
                    if (direct) return direct;
                    const ids = (el.getAttribute('aria-labelledby') || '').split(/\\s+/);
                    for (const id of ids) {
                        if (!id) continue;
                        const labelled = document.getElementById(id);
                        const text = (labelled?.textContent || '').trim();
                        if (text) return text;
                    }
                    // Only look a few levels up: the modal itself carries an
                    // aria-label ("Apply to ...") that is not the question text
                    let node = el.parentElement;
                    for (let depth = 0; node && depth < 4; depth++) {
                        const name = (node.getAttribute('aria-label') || '').trim();
                        if (name) return name;
                        node = node.parentElement;
                    }
                    return '';
                }"""
            )
        except Exception as e:
            logger.debug(f"Could not read the accessible name of the element: {e}")
            return ""
        return self._deduplicate_question_text((text or "").lower().strip())

    async def _select_dropdown_option(self, element: Any, text: str) -> bool:
        """Select dropdown option by visible text using robust matching (async).

        Tries exact label match, then normalized label (collapsed whitespace),
        then label without parenthetical (e.g., removes "(+1)"), and finally
        resolves to the option's 'value' when a label match is found.

        Returns:
            bool: True if an option was actually selected, False otherwise.
        """
        logger.debug(f"Selecting dropdown option: {text}")

        def normalize_label(s: str) -> str:
            try:
                import re as _re

                return _re.sub(r"\s+", " ", s or "").strip().lower()
            except Exception:
                return (s or "").strip().lower()

        label_candidates = []
        original = (text or "").strip()
        label_candidates.append(original)

        # Collapsed whitespace
        collapsed = " ".join(original.split())
        if collapsed not in label_candidates:
            label_candidates.append(collapsed)

        # Remove parenthetical like "(+1)"
        if "(" in original and ")" in original:
            base = original.split("(")[0].strip()
            if base and base not in label_candidates:
                label_candidates.append(base)

        # Normalize candidates for matching
        normalized_candidates = [normalize_label(c) for c in label_candidates]

        # First try direct label selection with primary candidate
        try:
            await element.select_option(label=label_candidates[0], timeout=3000)
            return True
        except Exception as e:
            logger.warning(f"Failed to select dropdown option '{text}': {e}")
            pass

        # Inspect available <option> elements to resolve the correct value
        try:
            matched_value = None
            opts_data = await element.locator("option").evaluate_all(
                "els => els.map(e => ({label: e.textContent || '', value: e.value || ''}))"
            )
            norm_to_value = [
                (normalize_label(d["label"]), d["value"]) for d in opts_data if d["label"].strip()
            ]

            # Exact match on normalized labels
            for cand in normalized_candidates:
                for opt_label_norm, opt_value in norm_to_value:
                    if opt_label_norm == cand:
                        matched_value = opt_value
                        break
                if matched_value:
                    break

            # Contains match if no exact
            if not matched_value:
                for cand in normalized_candidates:
                    for opt_label_norm, opt_value in norm_to_value:
                        if cand and cand in opt_label_norm:
                            matched_value = opt_value
                            break
                    if matched_value:
                        break

            if matched_value:
                await element.select_option(value=matched_value)
                return True
        except Exception as e:
            logger.warning(f"Failed to select dropdown option '{text}': {e}")
            pass

        # Final fallbacks: try label with collapsed whitespace, then value
        for cand in label_candidates[1:]:
            try:
                await element.select_option(label=cand)
                return True
            except Exception:
                continue

        try:
            await element.select_option(value=collapsed)
            return True
        except Exception as e:
            logger.warning(f"Failed to select dropdown option '{text}': {e}")
            await debug_capture(self.page, "dropdown_select_failed")
            return False

    async def _find_all_form_errors(self) -> List[str]:
        error_selectors = [
            ".artdeco-inline-feedback--error .artdeco-inline-feedback__message",
            ".artdeco-inline-feedback--error",
            "[role='alert'][data-test-form-element-error-messages]",
        ]
        errors_text: List[str] = []
        seen: set[str] = set()
        for selector in error_selectors:
            try:
                texts = await self.page.locator(selector).evaluate_all(
                    "els => els.map(e => e.textContent?.trim() || '')"
                )
                for txt in texts:
                    if txt and txt not in seen:
                        seen.add(txt)
                        errors_text.append(txt)
            except Exception as e:
                logger.debug(f"Failed to locate error elements with '{selector}': {e}")
        return errors_text

    async def _find_textbox_question_errors(self) -> List[Tuple[Any, str, str]]:
        """Find textbox fields that have validation errors and return details (async).

        Returns:
            List of tuples for each errored textbox field:
            - WebElement: the textbox (or textarea) element that needs correction
            - str: the question/label text associated with the field
            - str: the visible error message text
        """
        logger.debug("Searching for textbox validation errors in the Easy Apply modal")
        results: List[Tuple[Any, str, str]] = []

        form_container_selectors = [
            "xpath=.//*[contains(@class, 'fb-dash-form-element')]",
            "div[data-test-form-element]",
            "[data-test-single-line-text-form-component]",
            "[data-test-multiline-text-form-component]",
            "xpath=.//*[contains(@class, 'jobs-easy-apply-form-section__group')]",
        ]

        for selector in form_container_selectors:
            try:
                form_containers = await self.page.locator(selector).all()
                if form_containers:
                    logger.debug(
                        f"Found {len(form_containers)} form containers globally using selector: {selector}"
                    )
                    break
            except Exception:
                continue

        logger.debug(f"Found {len(form_containers)} form containers to inspect for errors")

        for section in form_containers:
            # Detect an error message within this section
            error_element: Any | None = None
            error_text: str = ""
            try:
                # Prefer the explicit message span inside the error container
                error_selectors = [
                    ".artdeco-inline-feedback--error .artdeco-inline-feedback__message",
                    ".artdeco-inline-feedback--error",
                    "[role='alert'][data-test-form-element-error-messages]",
                ]
                for selector in error_selectors:
                    loc = section.locator(selector)
                    cand_data = await loc.evaluate_all(
                        "els => els.map((e, i) => ({i, visible: e.offsetParent !== null, text: e.textContent?.trim() || ''}))"
                    )
                    match = next((d for d in cand_data if d["visible"] and d["text"]), None)
                    if match:
                        error_element = loc.nth(match["i"])
                        error_text = match["text"]
                        break
            except Exception:
                error_element = None

            if not error_element:
                continue

            # Find the textbox/textarea to correct within this section
            target_input: Any | None = None
            all_inputs_loc = section.locator(
                "input[type='text'], textarea, .artdeco-text-input--input"
            )
            vis_indices = await all_inputs_loc.evaluate_all(
                "els => els.map((e, i) => e.offsetParent !== null ? i : -1).filter(i => i >= 0)"
            )
            if vis_indices:
                target_input = all_inputs_loc.nth(vis_indices[0])

            if not target_input:
                # If no visible input found, skip this section
                logger.debug("Error found but no visible textbox in section; skipping")
                continue

            # Extract question/label text
            question_text = ""
            label: Any | None = None
            label_selectors = [
                "label",
                ".fb-dash-form-element__label",
                ".artdeco-text-input--label",
                "[data-test-single-typeahead-entity-form-title='true']",
            ]
            for selector in label_selectors:
                labels = await find_elements_safely(section, selector, "css selector")
                if labels:
                    label = labels[0]
                    break

            if label:
                try:
                    question_text = (await label.text_content() or "").lower().strip()
                    question_text = self._deduplicate_question_text(question_text)
                except Exception:
                    question_text = ""

            if not question_text:
                try:
                    alt = await target_input.get_attribute(
                        "aria-label"
                    ) or await target_input.get_attribute("placeholder")
                    if alt:
                        question_text = alt.strip()
                except Exception:
                    question_text = ""

            if not question_text:
                question_text = ""

            results.append((target_input, question_text, error_text))

        logger.debug(f"Textbox errors found: {len(results)}")
        return results

    async def _fill_textbox_question_errors(self) -> bool:
        """Find and try to fill with correct answers textbox question with errors (async)"""
        errors = await self._find_textbox_question_errors()
        if not errors:
            return False
        for error in errors:
            element, question_text, error_text = error
            logger.info(f"Answer textbox question with error: {question_text}. Error: {error_text}")
            answer = self.gpt_answerer.answer_question_textual_wide_range_with_error(
                question_text,
                error_text,
                await element.get_attribute("value"),
                self.previous_question_texts[:-1],
            )
            if self._is_no_info_answer(answer):
                raise NoInfoException(
                    f"Can't fix error: {error_text}. No info found for question: {question_text}"
                )
            answer = self.resume_anonymizer.deanonymize_text(answer)
            await element.fill(answer)
            await self._process_autocomplete_suggestions(element)
            self._save_questions(
                Question(question_type="text", question=question_text, answer=answer)
            )
        return True


if __name__ == "__main__":
    """Simple test for LinkedInEasyApplier functionality"""
    import asyncio
    from pathlib import Path

    import dotenv

    from config.app_config import TEST_MODE
    from config.constants import (
        COVER_LETTER_DIR,
        OUTPUT_DIR_LINKEDIN,
        RESUME_DIR,
        SEARCH_CONFIG_FILE,
    )
    from src.job_manager.linkedin.job_manager_linkedin import LinkedInJobManager
    from src.job_manager.resume_anonymizer import ResumeAnonymizer
    from src.llm.llm_manager import GPTAnswerer
    from src.pydantic_models.prompt_models import ResumeStructure
    from src.resume_builder.resume_generator import ResumeGenerator
    from src.resume_builder.resume_manager import ResumeManager
    from src.resume_builder.style_manager import StyleManager

    # Wrapper removed in migration; use raw Playwright page
    from src.utils.browser_utils import create_playwright_browser, save_browser_session

    RESUME_STRUCTURED_FILE = Path(RESUME_DIR) / "structured_resume.yaml"
    RESUME_TEXT_FILE = Path(RESUME_DIR) / "resume_text.txt"
    paused = False

    def build_linkedin_job_url(job_url_or_id: str | None = None) -> str:
        """Build a LinkedIn job URL from a full URL, numeric ID, or default value."""
        default_job_url = "https://www.linkedin.com/jobs/view/4460391419"
        if not job_url_or_id:
            return default_job_url
        job_url_or_id = job_url_or_id.strip()
        if not job_url_or_id:
            return default_job_url
        if job_url_or_id.isdigit():
            return f"https://www.linkedin.com/jobs/view/{job_url_or_id}"
        return job_url_or_id

    def normalize_test_job_from_parsed_page(parsed_job: Job | None, job_url: str) -> Job:
        """Ensure direct Easy Applier tests always have a usable Job object."""
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

    def collect_apply_result_metadata(
        easy_applier: Any, submitted_resume_path: Any
    ) -> dict[str, str]:
        """Collect metadata that should be persisted with standalone Easy Apply results."""
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

    async def check_pause():
        """Check if execution is paused and wait if needed"""
        global paused
        if paused:
            while paused:
                await asyncio.sleep(0.5)

    async def test_easy_applier(job_url_or_id: str | None = None):
        """Test LinkedInEasyApplier with a real LinkedIn job posting (async)"""
        logger.info("Starting LinkedInEasyApplier test...")

        # Test job URL
        job_url = build_linkedin_job_url(job_url_or_id)
        # Initialize Playwright browser
        try:
            browser, context, page = await create_playwright_browser()
            page = page
            logger.info("Playwright browser initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Playwright browser: {e}")
            return False

        try:
            # Navigate to job page and parse the actual job context before initializing LLM prompts.
            logger.info(f"Navigating to job page: {job_url}")
            await page.goto(job_url)
            await async_pause(3, 5)
            try:
                parser = LinkedInJobManager(page, "", None, None)
                parsed_job = await parser._get_detailed_job_description()
                test_job = normalize_test_job_from_parsed_page(parsed_job, job_url)
                logger.info(f"Parsed job page: {test_job.job_title} at {test_job.company_name}")
            except Exception as e:
                logger.warning(f"Failed to parse job page; using generic fallback job context: {e}")
                test_job = normalize_test_job_from_parsed_page(None, job_url)

            # Load secrets for LLM
            secrets = dotenv.dotenv_values(".env")
            llm_api_key = secrets.get("llm_api_key", "")
            llm_proxy = secrets.get("llm_proxy", "")

            # Initialize GPT answerer
            gpt_answerer = GPTAnswerer(llm_api_key, llm_proxy)
            resume_structured = load_yaml_file(RESUME_STRUCTURED_FILE)
            resume_structured = ResumeStructure(**resume_structured).model_dump()
            with open(RESUME_TEXT_FILE, "r") as f:
                resume_text = f.read()

            # Set resume anonymizer and anonymize the resume information
            resume_anonymizer = ResumeAnonymizer(resume_structured)
            resume_anonymizer.anonymize_personal_information()
            resume_structured = resume_anonymizer.resume_anonymized
            resume_text = resume_anonymizer.anonymize_text(resume_text)

            gpt_answerer.set_resume(resume_structured, resume_text)
            gpt_answerer.set_job(test_job.model_dump(), is_test=True)

            # Initialize resume generator manager (mock for testing)
            style_manager = StyleManager()
            resume_generator = ResumeGenerator(gpt_answerer, resume_anonymizer)
            resume_generator_manager = ResumeManager(llm_api_key, style_manager, resume_generator)

            # Initialize LinkedInEasyApplier
            easy_applier = LinkedInEasyApplier(
                page,
                gpt_answerer,
                resume_anonymizer,
                resume_generator_manager,
                check_pause,
                Path(OUTPUT_DIR_LINKEDIN) / "answers.yaml",
                RESUME_DIR,
                COVER_LETTER_DIR,
                test_mode=True,  # !
            )
            if easy_applier.ready_made_resume_path is None:
                resume_generator_manager.choose_style()

            # Test the apply_to_job method
            logger.info("Testing LinkedInEasyApplier.apply_to_job method...")
            result = await easy_applier.apply_to_job(test_job)
            apply_result, submitted_resume_path = result
            status, reason = apply_result

            result_manager = LinkedInJobManager(page, "", resume_anonymizer, None)
            result_manager.set_answerer_and_agent(gpt_answerer, None)
            result_manager.set_parameters(load_yaml_file(SEARCH_CONFIG_FILE) or {})
            await result_manager._handle_apply_result(
                apply_result,
                test_job,
                evaluation=collect_apply_result_metadata(easy_applier, submitted_resume_path),
            )
            logger.info("Standalone Easy Apply result persisted to output YAML")

            if easy_applier.already_applied_at_text:
                logger.info(
                    "Already-applied status date: "
                    f"{easy_applier.already_applied_at_text} ({easy_applier.already_applied_at})"
                )
            if submitted_resume_path:
                logger.info(f"Submitted resume path: {submitted_resume_path}")

            if status == "Success":
                logger.info("✅ LinkedInEasyApplier test completed successfully!")
                return True
            if status == "Skip" and reason == "Already applied to this job":
                logger.info(
                    "✅ LinkedInEasyApplier test detected already-applied job successfully!"
                )
                return True
            else:
                logger.error(f"❌ LinkedInEasyApplier test failed - result is {status}: {reason}")
                return False

        except Exception as e:
            logger.error(f"❌ LinkedInEasyApplier test failed with error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
        finally:
            # Keep browser open for manual inspection
            logger.info(
                "Test completed. Browser will remain open for 5 minutes for manual inspection..."
            )
            await async_pause(300, 300)
            try:
                await save_browser_session(context)
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass

    print("\nTesting full LinkedInEasyApplier functionality...")
    job_url_or_id = sys.argv[1] if len(sys.argv) > 1 else None
    success = asyncio.run(test_easy_applier(job_url_or_id))
    if success:
        print("✅ LinkedInEasyApplier test passed!")
    else:
        print("❌ LinkedInEasyApplier test failed!")
