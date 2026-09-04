import os
import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, List, Tuple

from playwright.sync_api import Page

from config.app_config import UPLOAD_RESUME
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
    get_current_page_testid,
    wait_for_page_transition,
)
from src.utils.utils import async_pause, get_ready_made_resume, load_yaml_file

INDEED_APPLY_BUTTON_SELECTOR = (
    "span.indeed-apply-status-not-applied button, "
    "button[aria-label*='Apply with Indeed'], "
    "button[aria-label*='Indeed Apply'], "
    "button#indeedApplyButton, "
    "button[data-jk], "
    ".ia-IndeedApplyButton"
)
INDEED_APPLY_MODAL_SELECTOR = "div.ia-BasePage, div[data-testid='ia-container']"
INDEED_NEXT_BUTTON_SELECTOR = "button[data-testid='continue-button'], button[data-testid^='hp-continue-button'], button[data-testid='ia-continueButton'], .ia-BasePage-component button:has-text('Continue'), button:has-text('Review your application'), button:has-text('Continue')"
INDEED_SUBMIT_BUTTON_SELECTOR = "button[data-testid='ia-submitButton'], button.ia-submitButton, button[data-testid='submit-application-button']"


class IndeedEasyApplier(BaseEasyApplier):
    """Handle Indeed 'Easily apply' application forms"""

    def __init__(
        self,
        page: Page,
        gpt_answerer: GPTAnswerer,
        resume_anonymizer: ResumeAnonymizer,
        resume_generator_manager: Any,
        pause_checker: Any,
        answers_file: Path,
        resume_dir: Path,
        cover_letter_dir: Path,
        test_mode: bool,
    ):
        self.page = page
        self.gpt_answerer = gpt_answerer
        self.resume_anonymizer = resume_anonymizer
        self.resume_generator_manager = resume_generator_manager
        self.pause_checker = pause_checker
        self.answers_file = answers_file
        self.resume_dir = resume_dir
        self.cover_letter_dir = cover_letter_dir
        self.test_mode = test_mode
        self.submitted_resume_path = None
        self.all_questions: List[Question] = self._load_questions()
        self.previous_question_texts: List[str] = []
        self.generated_resume_dir = Path(resume_dir) / "generated_resumes"
        self.ready_made_resume_path = get_ready_made_resume()

        logger.info("IndeedEasyApplier initialized")

    def set_page(self, page: Page) -> None:
        self.page = page

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def apply_to_job(self, job: Job) -> Tuple[Tuple[str, str], Any]:
        """Entry point - navigate to job page and apply"""
        logger.info(f"Navigating to Indeed job: {job.url}")
        emit_event(
            "easy_apply_started",
            f"Easy Apply started for {job.job_title}",
            job_title=job.job_title,
            company_name=job.company_name,
            url=job.url,
        )
        await self.page.goto(job.url)
        logger.info(f"Page loaded: {job.url}")
        await async_pause(1, 2)
        apply_result = await self.job_easy_apply(job)
        return apply_result, self.submitted_resume_path

    async def job_easy_apply(self, job: Job) -> Tuple[str, str]:
        """
        Attempt to apply to an Indeed job.
        Returns (result, cover_letter_text) where result is 'Success' | 'Skip' | 'Error'.
        """
        cover_letter = ""
        self.current_job = job
        try:
            apply_btn = await self._find_apply_button(job)
            if not apply_btn:
                logger.warning(f"No apply button found for: {job.job_title} at {job.company_name}")
                return "Skip", cover_letter

            try:
                async with self.page.context.expect_page(timeout=10000) as new_page_info:
                    await apply_btn.click()
                new_page = await new_page_info.value
                await new_page.wait_for_load_state("domcontentloaded")
                self.page = new_page
                logger.info("Application form opened in new tab, switched to it")
            except Exception:
                # No new tab — form is a modal on the current page
                logger.debug("No new tab opened, form is modal on current page")
                await async_pause(1, 2)

            await capture_page_screenshot(self.page, "easy-apply-opened")
            cover_letter = await self._fill_application_form(job)
            if self.test_mode:
                logger.info("TEST_MODE: skipping form submission")
                await self._discard_application()
                emit_event(
                    "easy_apply_completed",
                    f"Easy Apply completed for {job.job_title}",
                    job_title=job.job_title,
                    company_name=job.company_name,
                    url=job.url,
                )
                return "Success", cover_letter

            result = await self._submit_application()
            if result:
                emit_event(
                    "easy_apply_completed",
                    f"Easy Apply completed for {job.job_title}",
                    job_title=job.job_title,
                    company_name=job.company_name,
                    url=job.url,
                )
            return ("Success" if result else "Error"), cover_letter

        except StopRequested:
            raise
        except NoInfoException as e:
            logger.warning(f"Could not apply to {job.job_title} at {job.company_name}. Reason: {e}")
            return (
                "Skip",
                f"Could not apply to {job.job_title} at {job.company_name}. Reason: {e}",
            )
        except Exception as e:
            logger.error(f"Error applying to Indeed job {job.job_title}: {e}", exc_info=True)
            await capture_page_screenshot(self.page, "easy-apply-error")
            await debug_capture(self.page, "indeed_job_easy_apply_error")
            try:
                await self._discard_application()
            except Exception:
                logger.error(f"Error discarding application: {e}", exc_info=True)
            return "Error", cover_letter

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _find_apply_button(self, job: Job) -> Any:
        """Locate the Indeed apply button on the job detail page"""
        for selector in INDEED_APPLY_BUTTON_SELECTOR.split(", "):
            btn = await find_element_safely(self.page, selector.strip(), timeout=10000)
            if btn:
                logger.info(f"Found apply button: {selector.strip()}")
                return btn

        logger.warning("No apply button found on job page")
        return None

    async def _fill_application_form(self, job: Job) -> str:
        """Step through multi-page Indeed application form and fill fields"""
        cover_letter = ""
        max_steps = 10

        for step in range(max_steps):
            logger.info(f"Application form step {step + 1}")
            self.previous_question_texts = []

            if self.pause_checker:
                await self.pause_checker()

            # Fill visible form sections
            await self._fill_up(job)

            # Check if we're already on the submit page
            submit_btn = await find_element_safely(
                self.page, INDEED_SUBMIT_BUTTON_SELECTOR, timeout=1000
            )
            if submit_btn:
                logger.info("Reached submit page")
                break

            # Click next — find first *visible* button across the ordered selectors
            next_btn = await self._find_visible_next_button()
            if not next_btn:
                logger.warning("No next/submit button found")
                await debug_capture(self.page, "indeed_no_next_button")
                break

            current_page_testid = await get_current_page_testid(
                self.page,
                ["resume-selection-form", "profile-location-page", "relevant-experience-page"],
            )
            await next_btn.click()
            await async_pause(1, 2)
            await wait_for_page_transition(self.page, current_page_testid)
            try:
                await self.page.wait_for_load_state("domcontentloaded")
            except Exception as e:
                logger.warning(f"Error waiting for page to load: {e}")
            await async_pause(1, 2)

            # Retry up to 3 times if validation errors remain after clicking next
            for _ in range(3):
                fixed = await self._fill_textbox_question_errors()
                if not fixed:
                    break
                logger.info("Fixed textbox validation errors, retrying next button")
                next_btn = await self._find_visible_next_button()
                if not next_btn:
                    break
                await next_btn.click()
                await async_pause(2, 3)

        return cover_letter

    async def _find_visible_next_button(self) -> Any:
        """Return the first *visible* next/continue button, trying each selector in order."""
        for selector in INDEED_NEXT_BUTTON_SELECTOR.split(", "):
            selector = selector.strip()
            try:
                locator = self.page.locator(selector)
                count = await locator.count()
                for i in range(count):
                    btn = locator.nth(i)
                    if await btn.is_visible():
                        return btn
            except Exception:
                continue
        return None

    async def _fill_up(self, job: Job) -> None:
        """Fill visible form fields on the current step"""
        try:
            # Handle special-case pages first
            if await find_element_safely(
                self.page, "[data-testid='resume-selection-form']", timeout=1000
            ):
                await self.page.wait_for_load_state("domcontentloaded")
                await self._handle_resume_selection(job)
                return

            if await find_element_safely(
                self.page, "[data-testid='profile-location-page']", timeout=1000
            ):
                await self._fill_profile_location_page()
                return

            if await find_element_safely(
                self.page, "[data-testid='relevant-experience-page']", timeout=1000
            ):
                await self._fill_relevant_experience_page()
                return

            sections = await find_elements_safely(
                self.page,
                "div.ia-Questions-item, div[data-testid='ia-Questions-item'], div.ia-Qual-Questions-item",
            )
            for section in sections or []:
                try:
                    await self._process_form_section(section)
                except NoInfoException:
                    raise
        except NoInfoException:
            raise
        except Exception as e:
            logger.error(f"Error filling form step: {e}", exc_info=True)
            await debug_capture(self.page, "indeed_fill_form_error")

    async def _handle_resume_selection(self, job: Job) -> None:
        """Select resume: use Indeed Resume if UPLOAD_RESUME is False, otherwise upload a file"""
        try:
            if not UPLOAD_RESUME:
                indeed_resume_radio = await find_element_safely(
                    self.page,
                    "input[data-testid='resume-selection-structured-resume-radio-card-input']",
                    timeout=2000,
                )
                if indeed_resume_radio:
                    if not await indeed_resume_radio.is_checked():
                        indeed_resume_label = await find_element_safely(
                            self.page,
                            "label[data-testid='resume-selection-structured-resume-radio-card-label']",
                            timeout=2000,
                        )
                        if indeed_resume_label:
                            await indeed_resume_label.click()
                        else:
                            await indeed_resume_radio.click(force=True)
                        await async_pause(0.5, 1)
                    logger.info("Using Indeed Resume")
                    return
                logger.warning("Indeed Resume not available, falling back to file upload")

            upload_radio_input = await find_element_safely(
                self.page,
                "input[data-testid='resume-selection-file-resume-upload-radio-card-input']",
                timeout=2000,
            )
            if upload_radio_input and not await upload_radio_input.is_checked():
                # The radio input is visually hidden; click the visible label instead
                upload_label = await find_element_safely(
                    self.page,
                    "label[data-testid='resume-selection-file-resume-upload-radio-card-label']",
                    timeout=2000,
                )
                if upload_label:
                    await upload_label.click()
                    await async_pause(0.5, 1)
                    logger.info("Selected 'Upload a resume' radio option")

            file_input = await find_element_safely(
                self.page,
                "input[data-testid='resume-selection-file-resume-upload-radio-card-file-input']",
                timeout=2000,
            )
            if not file_input:
                logger.warning("Resume file input not found on resume selection page")
                return

            if self.ready_made_resume_path is not None:
                abs_path = os.path.abspath(str(self.ready_made_resume_path))
                await file_input.set_input_files(abs_path)
                logger.info(f"Uploaded ready-made resume: {abs_path}")
            else:
                await self._create_and_upload_resume(file_input, job)
        except Exception as e:
            logger.error(f"Error handling resume selection page: {e}", exc_info=True)
            await debug_capture(self.page, "indeed_resume_selection_error")

    async def _fill_profile_location_page(self) -> None:
        """Fill the 'Review your location details' profile page using resume data"""
        try:
            personal = {}
            if self.gpt_answerer and hasattr(self.gpt_answerer, "resume_structured"):
                personal = self.gpt_answerer.resume_structured.get("personal_information", {})

            postal_code = str(personal.get("zip_code", "") or "")
            city = str(personal.get("city", "") or "")
            address = str(personal.get("address", "") or "")

            if postal_code:
                field = await find_element_safely(
                    self.page,
                    "input[data-testid='location-fields-postal-code-input']",
                    timeout=2000,
                )
                if field:
                    await field.fill(postal_code)
                    logger.debug(f"Filled postal code: {postal_code}")

            if city:
                field = await find_element_safely(
                    self.page, "input[data-testid='location-fields-locality-input']", timeout=2000
                )
                if field:
                    await field.fill(city)
                    logger.debug(f"Filled city: {city}")

            if address:
                field = await find_element_safely(
                    self.page, "input[data-testid='location-fields-address-input']", timeout=2000
                )
                if field:
                    await field.fill(address)
                    logger.debug(f"Filled street address: {address}")

        except Exception as e:
            logger.error(f"Error filling profile location page: {e}", exc_info=True)
            await debug_capture(self.page, "indeed_profile_location_error")

    async def _fill_relevant_experience_page(self) -> None:
        """Fill the 'relevant experience' page — handles two variants:
        1. Radio card selection: 'Highlight a job that shows relevant experience'
        2. Text inputs: 'Enter a job that shows relevant experience'
        """
        try:
            # Variant 1: radio card selection
            radio_group = await find_element_safely(
                self.page, "[data-testid='RadioCardGroup']", timeout=2000
            )
            if radio_group:
                await self._handle_relevant_experience_radio_cards()
                return

            # Variant 2: free-text job title / company inputs
            experience_details = []
            if self.gpt_answerer and hasattr(self.gpt_answerer, "resume_structured"):
                experience_details = self.gpt_answerer.resume_structured.get(
                    "experience_details", []
                )

            position = ""
            company = ""
            if experience_details:
                most_recent = experience_details[0]
                position = str(most_recent.get("position", "") or "")
                company = str(most_recent.get("company", "") or "")

            title_input = await find_element_safely(
                self.page, "input[data-testid='job-title-input']", timeout=2000
            )
            if title_input and position:
                current_value = await title_input.input_value()
                if not current_value:
                    await title_input.fill(position)
                    logger.debug(f"Filled relevant experience job title: {position}")
                else:
                    logger.debug(f"Relevant experience job title already filled: {current_value}")

            company_input = await find_element_safely(
                self.page, "input[data-testid='company-name-input']", timeout=2000
            )
            if company_input and company:
                current_value = await company_input.input_value()
                if not current_value:
                    await company_input.fill(company)
                    logger.debug(f"Filled relevant experience company: {company}")
                else:
                    logger.debug(f"Relevant experience company already filled: {current_value}")

        except Exception as e:
            logger.error(f"Error filling relevant experience page: {e}", exc_info=True)
            await debug_capture(self.page, "indeed_relevant_experience_error")

    async def _handle_relevant_experience_radio_cards(self) -> None:
        """Select the most relevant work experience radio card.

        Prefers the first WorkExperienceCard (most recent job from the resume).
        Falls back to 'Apply without relevant job' if no work experience cards exist.
        """
        try:
            work_cards = await find_elements_safely(
                self.page,
                "input[data-testid='WorkExperienceCard-input']",
            )
            if work_cards:
                first_card = work_cards[0]
                if not await first_card.is_checked():
                    # Radio inputs are visually hidden — click the corresponding label
                    card_id = await first_card.get_attribute("id")
                    if card_id:
                        label = await find_element_safely(
                            self.page, f"label[for='{card_id}']", timeout=2000
                        )
                        if label:
                            await label.click()
                        else:
                            await first_card.click(force=True)
                    else:
                        await first_card.click(force=True)
                    await async_pause(0.5, 1)

                # Log which card was selected
                card_container = await find_elements_safely(
                    self.page,
                    "[data-testid='WorkExperienceCard']",
                )
                if card_container:
                    title_el = await find_element_safely(
                        card_container[0],
                        "[data-testid='WorkExperienceCardHeader-title']",
                        timeout=500,
                    )
                    subtitle_el = await find_element_safely(
                        card_container[0],
                        "[data-testid='WorkExperienceCardHeader-subtitle']",
                        timeout=500,
                    )
                    title = await get_clean_text(title_el) if title_el else ""
                    subtitle = await get_clean_text(subtitle_el) if subtitle_el else ""
                    logger.info(f"Selected relevant experience card: '{title}' at '{subtitle}'")
            else:
                logger.info(
                    "No WorkExperienceCard options found; "
                    "'Apply without relevant job' remains selected"
                )
        except Exception as e:
            logger.error(f"Error handling relevant experience radio cards: {e}", exc_info=True)
            await debug_capture(self.page, "indeed_relevant_experience_radio_error")

    async def _process_form_section(self, section: Any) -> None:
        if await self._find_and_handle_hierarchical_select(section):
            logger.debug("Handled hierarchical select question")
            return
        await super()._process_form_section(section)

    # Country names that differ from the option labels Indeed renders
    _COUNTRY_ALIASES = {
        "USA": "united states",
        "US": "united states",
        "UNITED STATES OF AMERICA": "united states",
        "UK": "united kingdom",
        "GB": "united kingdom",
        "GREAT BRITAIN": "united kingdom",
    }

    async def _match_country_option(self, country_select: Any, country_raw: str) -> str:
        """Resolve a resume country to one of the select's option values (async).

        Matches the value (usually an ISO code such as "CH") and the visible
        label, so any country Indeed offers is selectable. Returns "" when the
        country is unknown or missing.
        """
        if not country_raw:
            return ""

        wanted = {country_raw.lower()}
        alias = self._COUNTRY_ALIASES.get(country_raw.upper())
        if alias:
            wanted.add(alias)

        try:
            options = await country_select.locator("option").evaluate_all(
                "els => els.map(e => ({value: e.value || '', label: (e.textContent || '').trim()}))"
            )
        except Exception as e:
            logger.debug(f"Could not read the options of the country select: {e}")
            return ""

        for option in options:
            if not option["value"]:
                continue
            if option["value"].lower() in wanted or option["label"].lower() in wanted:
                return option["value"]
        return ""

    async def _find_and_handle_hierarchical_select(self, section: Any) -> bool:
        """Handle Indeed's two-level country → state/province hierarchical select."""
        country_select = await find_element_safely(
            section, "select#profile-countryState, select[name='profile-countryState']", timeout=500
        )
        if not country_select:
            return False

        try:
            personal = {}
            if self.gpt_answerer and hasattr(self.gpt_answerer, "resume_structured"):
                personal = self.gpt_answerer.resume_structured.get("personal_information", {})

            country_raw = str(personal.get("country", "") or "").strip()
            current_country = await country_select.input_value()
            country_value = await self._match_country_option(country_select, country_raw)

            if not country_value:
                # Never fall back to a hard-coded country: an unrecognised one used
                # to silently become the US
                if country_raw:
                    logger.warning(
                        f"Country '{country_raw}' is not among the options of the country "
                        f"select, keeping the current value '{current_country}'"
                    )
                country_value = current_country
            elif current_country != country_value:
                await country_select.select_option(value=country_value)
                await async_pause(0.5, 1)
                logger.debug(f"Selected country: {country_value}")

            # Find the dependent state dropdown (id starts with 'countryState_')
            state_select = await find_element_safely(
                section,
                f"select#countryState_{country_value}, select[id^='countryState_']",
                timeout=2000,
            )
            if not state_select:
                logger.debug("No dependent state dropdown found")
                return True

            current_state = await state_select.input_value()
            if current_state:
                logger.debug(f"State already selected: {current_state}")
                return True

            state_raw = str(personal.get("state_area_region", "") or "").strip()
            if not state_raw:
                logger.debug("No state info in resume, skipping state selection")
                return True

            # Try selecting by value (abbreviation) first, then by label (full name)
            options = await find_elements_safely(state_select, "option")
            option_values = [await o.get_attribute("value") or "" for o in options]
            option_texts = [await get_clean_text(o) for o in options]

            # Exact match on abbreviation
            for val in option_values:
                if val and val.upper() == state_raw.upper():
                    await state_select.select_option(value=val)
                    logger.debug(f"Selected state by abbreviation: {val}")
                    return True

            # Match by full text
            for text in option_texts:
                if text and text.lower() == state_raw.lower():
                    await state_select.select_option(label=text)
                    logger.debug(f"Selected state by label: {text}")
                    return True

            # Partial match
            for text in option_texts:
                if text and (
                    state_raw.lower() in text.lower() or text.lower() in state_raw.lower()
                ):
                    await state_select.select_option(label=text)
                    logger.debug(f"Selected state by partial match: {text}")
                    return True

            logger.warning(f"Could not match state '{state_raw}' to any option")
        except Exception as e:
            logger.error(f"Error handling hierarchical select: {e}", exc_info=True)
            await debug_capture(self.page, "indeed_hierarchical_select_error")
        return True

    async def _handle_terms_of_service(self, section: Any) -> bool:
        return False

    async def _find_and_handle_date_question(self, section: Any) -> bool:
        """Fill date input fields (MM/DD/YYYY format) using cache or LLM"""
        date_input = await find_element_safely(
            section,
            "input[placeholder='MM/DD/YYYY'], input[id^='date-question-input']",
            timeout=500,
        )
        if not date_input:
            return False
        question_text = await get_clean_text(section)
        try:
            self.previous_question_texts.append(question_text)
            cached = self._find_cached_question(question_text, "date")
            existing_answer = cached.answer if cached else None
            if existing_answer:
                answer = existing_answer
                logger.debug(f"Using cached date answer for '{question_text}': '{answer}'")
            else:
                raw = self.gpt_answerer.answer_question_date(
                    question_text, self.previous_question_texts[:-1]
                )
                if self._is_no_info_answer(raw):
                    raise NoInfoException(f"No info found for question: {question_text}")
                answer = self._parse_date_to_mmddyyyy(raw)
                self._save_questions(
                    Question(question_type="date", question=question_text, answer=answer)
                )
            await date_input.fill(answer)
            logger.debug(f"Filled date field '{question_text}' with '{answer}'")
        except NoInfoException:
            raise
        except Exception as e:
            logger.warning(f"Error handling date field section: {e}")
            await debug_capture(self.page, "indeed_date_field_error")
            return False
        return True

    def _parse_date_to_mmddyyyy(self, date_str: str) -> str:
        """Try to parse a date string and return it in MM/DD/YYYY format"""
        formats = [
            "%m/%d/%Y",
            "%Y-%m-%d",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d/%m/%Y",
            "%m-%d-%Y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt).strftime("%m/%d/%Y")
            except ValueError:
                continue
        logger.warning(f"Could not parse date '{date_str}', using as-is")
        return date_str

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
        """Check if a form field is a numeric (number) question on Indeed"""
        field_type = (await field.get_attribute("type") or "").lower()
        field_id = (await field.get_attribute("id") or "").lower()
        inputmode = (await field.get_attribute("inputmode") or "").lower()
        if field_type == "number" or inputmode == "numeric" or field_id.startswith("number-input-"):
            return True
        q = question_text.lower()
        return any(
            re.search(r"\b" + re.escape(kw) + r"\b", q) for kw in self._NUMERIC_QUESTION_KEYWORDS
        )

    async def _find_and_handle_textbox_question(self, section: Any) -> bool:
        """Fill appropriate textbox using cache or LLM"""
        text_input = await find_element_safely(
            section, "input[type='text'], input[type='number'], textarea", timeout=500
        )
        if not text_input:
            return False
        question_text = await get_clean_text(section)
        try:
            self.previous_question_texts.append(question_text)
            is_numeric = await self._is_numeric_field(text_input, question_text)
            question_type = "numeric" if is_numeric else "text"
            cached = self._find_cached_question(question_text, question_type)
            existing_answer = cached.answer if cached else None
            if existing_answer:
                answer = existing_answer
                logger.debug(f"Using cached answer for '{question_text}': '{answer}'")
            elif is_numeric:
                answer = self.gpt_answerer.answer_question_numeric(
                    question_text, self.previous_question_texts[:-1]
                )
                if self._is_no_info_answer(answer):
                    raise NoInfoException(f"No info found for question: {question_text}")
                self._save_questions(
                    Question(question_type="numeric", question=question_text, answer=answer)
                )
            else:
                answer = self.gpt_answerer.answer_question_textual_wide_range(
                    question_text, self.previous_question_texts[:-1]
                )
                if self._is_no_info_answer(answer):
                    raise NoInfoException(f"No info found for question: {question_text}")
                answer = self.resume_anonymizer.deanonymize_text(answer)
                self._save_questions(
                    Question(question_type="text", question=question_text, answer=answer)
                )
            await text_input.fill(answer)
            logger.debug(
                f"Filled {'numeric' if is_numeric else 'text'} field '{question_text}' with '{answer}'"
            )
        except NoInfoException:
            raise
        except Exception as e:
            logger.warning(f"Error handling text field section: {e}")
            await debug_capture(self.page, "indeed_text_field_error")
            return False
        return True

    async def _find_and_handle_checkbox_question(self, section: Any) -> bool:
        """Select appropriate checkboxes (multi-select) using LLM"""
        checkbox = await find_element_safely(section, "input[type='checkbox']", timeout=500)
        if not checkbox:
            return False

        try:
            question_text = await get_clean_text(section)
            checkboxes = await find_elements_safely(section, "input[type='checkbox']")
            if not checkboxes:
                return False

            checkbox_data = []
            option_texts = []
            for cb in checkboxes:
                cb_id = await cb.get_attribute("id")
                label_text = ""
                if cb_id:
                    label_el = await find_element_safely(
                        section, f"label[for='{cb_id}']", timeout=1000
                    )
                    if label_el:
                        label_text = await get_clean_text(label_el)
                if label_text:
                    checkbox_data.append((cb, label_text))
                    option_texts.append(label_text)

            if not option_texts:
                return False

            # Remove options from question text
            for option in sorted(option_texts, key=lambda x: len(x), reverse=True):
                question_text = question_text[::-1].replace(option[::-1], "", 1)[::-1]
            question_text = re.sub(
                r"Clear your answer(s)?", "", question_text, flags=re.IGNORECASE
            ).strip()

            if question_text:
                self.previous_question_texts.append(question_text)

            cached = self._find_cached_question(question_text, "checkbox")
            existing_answer = cached.answer if cached else None
            if existing_answer:
                selected_options = (
                    existing_answer if isinstance(existing_answer, list) else [existing_answer]
                )
                logger.debug(f"Using cached checkboxes for '{question_text}': {selected_options}")
            else:
                selected_options = self.gpt_answerer.select_many_answers_from_options(
                    question_text, option_texts, self.previous_question_texts[:-1]
                )
                self._save_questions(
                    Question(
                        question_type="checkbox",
                        question=question_text,
                        answer=selected_options,
                    )
                )
            logger.debug(f"Selected checkboxes: {selected_options}")

            for cb, label_text in checkbox_data:
                if any(
                    sel.lower() in label_text.lower() or label_text.lower() in sel.lower()
                    for sel in selected_options
                    if not self._is_no_info_answer(sel)
                ):
                    if not await cb.is_checked():
                        cb_id = await cb.get_attribute("id")
                        if cb_id:
                            label_el = await find_element_safely(
                                section, f"label[for='{cb_id}']", timeout=1000
                            )
                            if label_el:
                                await label_el.click()
                                logger.debug(f"Checked checkbox via label: '{label_text}'")
                                continue
                        await cb.click()
                        logger.debug(f"Checked checkbox: '{label_text}'")
        except Exception as e:
            logger.warning(f"Error handling checkbox section: {e}")
            await debug_capture(self.page, "indeed_checkbox_error")
            return False
        return True

    async def _find_and_handle_radio_question(self, section: Any) -> bool:
        """Select appropriate radio option using LLM"""
        radio = await find_element_safely(section, "input[type='radio']", timeout=500)
        if not radio:
            return False

        try:
            question_text = await get_clean_text(section)
            radios = await find_elements_safely(section, "input[type='radio']")
            if not radios:
                return False
            option_texts = []
            for radio in radios:
                label_id = await radio.get_attribute("id")
                if label_id:
                    label_el = await find_element_safely(
                        section, f"label[for='{label_id}']", timeout=1000
                    )
                    option_texts.append(await get_clean_text(label_el) if label_el else "")
                else:
                    option_texts.append("")

            # Remove options from question text
            for option in sorted(option_texts, key=lambda x: len(x), reverse=True):
                question_text = question_text[::-1].replace(option[::-1], "", 1)[::-1]
            question_text = re.sub(
                r"Clear your answer(s)?", "", question_text, flags=re.IGNORECASE
            ).strip()

            if question_text:
                self.previous_question_texts.append(question_text)

            cached = self._find_cached_question(question_text, "radio")
            existing_answer = cached.answer if cached else None
            if existing_answer:
                answer = existing_answer
                logger.debug(f"Using cached radio answer for '{question_text}': '{answer}'")
            else:
                answer = self.gpt_answerer.select_one_answer_from_options(
                    question_text, option_texts, self.previous_question_texts[:-1]
                )
                if self._is_no_info_answer(answer):
                    raise NoInfoException(f"No info found for question: {question_text}")
                self._save_questions(
                    Question(question_type="radio", question=question_text, answer=answer)
                )

            async def click_radio(radio: Any) -> None:
                """Click via label when the input is visually hidden, else direct click."""
                radio_id = await radio.get_attribute("id")
                if radio_id:
                    label_el = await find_element_safely(
                        section, f"label[for='{radio_id}']", timeout=1000
                    )
                    if label_el and await label_el.is_visible():
                        await label_el.click()
                        return
                await radio.click()

            # Exact match first to avoid substring false positives (e.g. "male" in "female")
            for radio, option in zip(radios, option_texts):
                if answer.lower() == option.lower():
                    await click_radio(radio)
                    logger.debug(f"Selected radio '{option}'")
                    return True
            for radio, option in zip(radios, option_texts):
                if answer.lower() in option.lower():
                    await click_radio(radio)
                    logger.debug(f"Selected radio '{option}'")
                    return True
            # Fallback: click first option
            await click_radio(radios[0])
        except NoInfoException:
            raise
        except Exception as e:
            logger.warning(f"Error handling radio section: {e}")
            await debug_capture(self.page, "indeed_radio_error")
            return False
        return True

    async def _find_and_handle_dropdown_question(self, section: Any) -> bool:
        """Select appropriate dropdown option using LLM"""
        dropdown = await find_element_safely(section, "select", timeout=500)
        if not dropdown:
            return False

        try:
            question_text = await get_clean_text(section)
            if not question_text:
                return False

            options = await find_elements_safely(section, "select option")
            option_texts = [await get_clean_text(o) for o in options]

            # Remove options from question text
            for option in sorted(option_texts, key=lambda x: len(x), reverse=True):
                question_text = question_text[::-1].replace(option[::-1], "", 1)[::-1]
            question_text = re.sub(
                r"Clear your answer(s)?", "", question_text, flags=re.IGNORECASE
            ).strip()

            self.previous_question_texts.append(question_text)

            cached = self._find_cached_question(question_text, "dropdown")
            existing_answer = cached.answer if cached else None
            if existing_answer:
                answer = existing_answer
                logger.debug(f"Using cached dropdown answer for '{question_text}': '{answer}'")
            else:
                answer = self.gpt_answerer.select_one_answer_from_options(
                    question_text, option_texts, self.previous_question_texts[:-1]
                )
                if self._is_no_info_answer(answer):
                    raise NoInfoException(f"No info found for question: {question_text}")
                self._save_questions(
                    Question(question_type="dropdown", question=question_text, answer=answer)
                )
            # Exact match first to avoid substring false positives
            for opt_text in option_texts:
                if answer.lower() == opt_text.lower():
                    await dropdown.select_option(label=opt_text)
                    logger.debug(f"Selected dropdown option '{opt_text}'")
                    return True
            for opt_text in option_texts:
                if answer.lower() in opt_text.lower():
                    await dropdown.select_option(label=opt_text)
                    logger.debug(f"Selected dropdown option '{opt_text}'")
                    return True
            # Fallback: skip default/empty option and pick the first real one
            if len(option_texts) > 1:
                await dropdown.select_option(label=option_texts[1])
        except NoInfoException:
            raise
        except Exception as e:
            logger.warning(f"Error handling dropdown section: {e}")
            await debug_capture(self.page, "indeed_dropdown_error")
            return False
        return True

    async def _submit_application(self) -> bool:
        """Click the final submit button"""
        try:
            captcha = await find_element_safely(self.page, "[data-testid='captcha']", timeout=20000)
            if captcha:
                logger.warning("Captcha detected before submission — pausing for manual solve")
                while True:
                    if not await find_element_safely(
                        self.page, "[data-testid='captcha']", timeout=1000
                    ):
                        break
                    response = await self.page.locator("#g-recaptcha-response").input_value()
                    if response:
                        break
                    await async_pause(3, 3)

            submit_btn = await find_element_safely(
                self.page, INDEED_SUBMIT_BUTTON_SELECTOR, timeout=20000
            )
            if not submit_btn:
                logger.error("Submit button not found")
                await debug_capture(self.page, "indeed_submit_button_not_found")
                return False

            await submit_btn.click()
            await async_pause(2, 4)
            logger.info("Application submitted on Indeed")
            return True
        except Exception as e:
            logger.error(f"Error submitting Indeed application: {e}", exc_info=True)
            await debug_capture(self.page, "indeed_submit_error")
            return False

    async def _discard_application(self) -> None:
        """Close/discard the current Indeed application modal"""
        try:
            close_selectors = [
                "button[data-testid='ExitLinkWithModalComponent-exitButton']",
                "button[aria-label='Close']",
                "button.ia-CloseButton",
                "button[data-testid='ia-closeButton']",
            ]
            for selector in close_selectors:
                btn = await find_element_safely(self.page, selector, timeout=1000)
                if btn:
                    await btn.click()
                    await async_pause(1, 2)
                    # Handle "Save application progress" dialog if it appears
                    dont_save = await find_element_safely(
                        self.page, "button:has-text('Don\\'t save')", timeout=2000
                    )
                    if dont_save:
                        await dont_save.click()
                        logger.info("Dismissed save dialog with 'Don't save'")
                    logger.info("Indeed application discarded")
                    return
        except Exception as e:
            logger.warning(f"Could not discard Indeed application: {e}")
            await debug_capture(self.page, "indeed_discard_error")

    async def _fill_textbox_question_errors(self) -> bool:
        """Find textbox fields with validation errors and re-fill them using LLM."""
        results: List[Tuple[Any, str, str]] = []

        # Find all invalid text inputs on the page
        invalid_inputs = await find_elements_safely(
            self.page,
            "input[aria-invalid='true'], textarea[aria-invalid='true']",
        )
        if not invalid_inputs:
            return False

        for input_el in invalid_inputs:
            try:
                # Get the error message via aria-describedby → find the error element
                described_by = await input_el.get_attribute("aria-describedby") or ""
                error_text = ""
                for desc_id in described_by.split():
                    if "error" in desc_id:
                        error_el = self.page.locator(f"[id='{desc_id}']")
                        if await error_el.count():
                            error_text = (await error_el.text_content() or "").strip()
                            break

                if not error_text:
                    continue

                # Get the question label text
                input_id = await input_el.get_attribute("id") or ""
                question_text = ""
                if input_id:
                    label_el = self.page.locator(f"label[for='{input_id}']")
                    if await label_el.count():
                        question_text = (await label_el.text_content() or "").strip()

                if not question_text:
                    # Fallback: aria-label or name attribute
                    question_text = (
                        await input_el.get_attribute("aria-label")
                        or await input_el.get_attribute("name")
                        or ""
                    ).strip()

                results.append((input_el, question_text, error_text))
            except Exception as e:
                logger.warning(f"Error inspecting invalid input: {e}")
                continue

        if not results:
            return False

        for element, question_text, error_text in results:
            logger.info(f"Fixing textbox error for '{question_text}': {error_text}")
            try:
                current_value = await element.input_value()
                answer = self.gpt_answerer.answer_question_textual_wide_range_with_error(
                    question_text,
                    error_text,
                    current_value,
                    self.previous_question_texts,
                )
                if self._is_no_info_answer(answer):
                    raise NoInfoException(
                        f"Can't fix error: {error_text}. No info for question: {question_text}"
                    )
                answer = self.resume_anonymizer.deanonymize_text(answer)
                await element.fill(answer)
                self._save_questions(
                    Question(question_type="text", question=question_text, answer=answer)
                )
                logger.debug(f"Re-filled '{question_text}' with '{answer}'")
            except NoInfoException:
                raise
            except Exception as e:
                logger.warning(f"Error fixing textbox field '{question_text}': {e}")
                await debug_capture(self.page, "indeed_textbox_error_fix_error")
                return False

        return True


if __name__ == "__main__":
    """Simple test for IndeedEasyApplier functionality"""
    import asyncio
    from pathlib import Path

    import dotenv

    import config.app_config as app_config

    app_config.DEBUG_MODE = True

    from config.constants import COVER_LETTER_DIR, OUTPUT_DIR_INDEED, RESUME_DIR
    from src.job_manager.resume_anonymizer import ResumeAnonymizer
    from src.llm.llm_manager import GPTAnswerer
    from src.pydantic_models.job_models import Job
    from src.pydantic_models.prompt_models import ResumeStructure
    from src.resume_builder.resume_generator import ResumeGenerator
    from src.resume_builder.resume_manager import ResumeManager
    from src.resume_builder.style_manager import StyleManager
    from src.utils.browser_utils import create_playwright_browser, save_browser_session

    RESUME_STRUCTURED_FILE = Path(RESUME_DIR) / "structured_resume.yaml"
    RESUME_TEXT_FILE = Path(RESUME_DIR) / "resume_text.txt"
    paused = False

    async def check_pause():
        """Check if execution is paused and wait if needed"""
        global paused
        if paused:
            while paused:
                await asyncio.sleep(0.5)

    async def test_indeed_easy_applier():
        """Test IndeedEasyApplier with a real Indeed job posting (async)"""
        logger.info("Starting IndeedEasyApplier test...")

        # Test job URL
        job_url = "https://www.indeed.com/viewjob?jk=7f6c960d05bd4700"

        # Initialize Playwright browser
        try:
            browser, context, page = await create_playwright_browser()
            logger.info("Playwright browser initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Playwright browser: {e}")
            return False

        # Create test job object
        test_job = Job(
            job_title="Junior Software Developer",
            company_name="Example Corp",
            location="Remote",
            url=job_url,
            job_description="Entry-level software developer role working on web applications.",
            apply_method="Easy Apply",
        )

        try:
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

            # Initialize resume generator manager
            style_manager = StyleManager()
            resume_generator = ResumeGenerator(gpt_answerer, resume_anonymizer)
            resume_generator_manager = ResumeManager(llm_api_key, style_manager, resume_generator)

            # Initialize IndeedEasyApplier
            easy_applier = IndeedEasyApplier(
                page,
                gpt_answerer,
                resume_anonymizer,
                resume_generator_manager,
                check_pause,
                Path(OUTPUT_DIR_INDEED) / "answers.yaml",
                RESUME_DIR,
                COVER_LETTER_DIR,
                test_mode=True,
            )
            if easy_applier.ready_made_resume_path is None:
                resume_generator_manager.choose_style()

            # Test the apply_to_job method
            logger.info("Testing IndeedEasyApplier.apply_to_job method...")
            result = await easy_applier.apply_to_job(test_job)

            if result[0] == "Success":
                logger.info("✅ IndeedEasyApplier test completed successfully!")
                return True
            else:
                logger.error(f"❌ IndeedEasyApplier test failed - result: {result[0]}")
                return False

        except Exception as e:
            logger.error(f"❌ IndeedEasyApplier test failed with error: {e}")
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

    print("\nTesting full IndeedEasyApplier functionality...")
    success = asyncio.run(test_indeed_easy_applier())
    if success:
        print("✅ IndeedEasyApplier test passed!")
    else:
        print("❌ IndeedEasyApplier test failed!")
