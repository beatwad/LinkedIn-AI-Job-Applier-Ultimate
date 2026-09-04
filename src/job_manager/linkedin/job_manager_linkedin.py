import re
import time
import traceback
from datetime import timedelta
from inspect import isawaitable
from pathlib import Path
from typing import Any, Dict, List, Tuple

from playwright.sync_api import Page

from config.app_config import (
    COLLECT_INFO_MODE,
    EASY_APPLY_ONLY_MODE,
    MAX_APPLIES_NUM,
    MINIMUM_WAIT_TIME_SEC,
    MONKEY_MODE,
    TEST_MODE,
)
from config.constants import COVER_LETTER_DIR, OUTPUT_DIR_LINKEDIN, RESUME_DIR, SEARCH_CONFIG_FILE
from config.logger_config import logger
from src.dashboard.runtime import StopRequested, emit_event
from src.job_manager.job_manager import BaseJobManager
from src.job_manager.linkedin.easy_applier_linkedin import LinkedInEasyApplier
from src.pydantic_models.job_models import Job
from src.utils.browser_utils import (
    debug_capture,
    find_element_safely,
    find_elements_safely,
    get_clean_text,
    get_element_attribute_safely,
    get_element_text,
    is_scrollable,
    safe_click,
    scroll_slowly,
)
from src.utils.runtime_control import ShutdownState, runtime_controller
from src.utils.utils import async_pause, load_yaml_file, sanitize_text

search_config = load_yaml_file(SEARCH_CONFIG_FILE)
logger.info(f"Maximum allowed number of applications: {MAX_APPLIES_NUM}")

# External ATSes browser-use can't reliably automate: stale element indices
# cause infinite step loops with no exception. Matched as URL substrings.
EXTERNAL_APPLY_SKIP_ATSES: tuple[str, ...] = (
    "phenom",
    "successfactors",
)


class LinkedInJobManager(BaseJobManager):
    """Class for searching and sending applications to employers"""

    def __init__(
        self, page: Page, linkedin_email: str, resume_anonymizer: Any, search_component: Any
    ):
        logger.info("Initializing LinkedInJobManager")
        self.page = page
        self.email = linkedin_email
        self.resume_anonymizer = resume_anonymizer
        self.search_component = search_component
        self.llm_answerer_component = None
        self.llm_agent_component = None
        self.resume_generator_manager = None
        self.submitted_resume_path = None
        self.already_applied_at = None
        self.already_applied_at_text = None
        self.pause_checker = None
        self.jobs_no_info = (
            []
        )  # vacancies to which applications were not sent due to missing information
        self.job_key_skills = []  # key skills according to employer's opinion
        self.interesting_jobs = []
        self.page_num = 0
        self.resume_vac_page_num = -1  # number of pages with vacancies similar to resume
        self.error_num = 0
        self.total_applies_num = 0
        self.total_discovered_jobs = 0
        self.resume_recommendations = ""

        logger.info("LinkedInJobManager successfully initialized")

    async def get_vacancies_from_page(self) -> List[Any]:
        """Parse job vacancies from current LinkedIn page (async)"""
        logger.info(f"Parsing job vacancies from LinkedIn page {self.page_num}")
        vacancies = []

        try:
            # Scroll to load all job listings on the page
            await self._scroll_to_load_jobs()

            # Find all job listing elements on the current page using multiple selectors
            job_selectors = [
                ".scaffold-layout__list [data-view-name='job-card'][data-job-id]",
                ".scaffold-layout__list .job-card-job-posting-card-wrapper[data-job-id]",
                ".scaffold-layout__list div[data-job-id]",
                ".jobs-search-results__list-item",
                ".job-card-container",
                ".base-card",
                ".job-card-list__entity-lockup",
                ".scaffold-layout__list-item",
                "div[data-job-id]",
                "//*[starts-with(@class, 'flex-grow-1')]",
            ]

            seen_job_keys = set()
            for selector in job_selectors:
                by = "xpath" if selector.startswith("//") else "css selector"
                elements = await find_elements_safely(self.page, selector, by)
                if not elements:
                    continue
                logger.debug(f"Found {len(elements)} job elements using selector: {selector}")

                selector_vacancies = []
                for job_element in elements:
                    try:
                        if await self._is_applied_job_card(job_element):
                            logger.info("Skipping already-applied LinkedIn job card")
                            continue
                        job_url = await self._extract_job_url(job_element)
                        if job_url:
                            match = re.search(r"/jobs/view/(\d+)", job_url)
                            job_id = match.group(1) if match else None
                            job_key = job_id or job_url
                            if job_key in seen_job_keys:
                                continue
                            seen_job_keys.add(job_key)
                            selector_vacancies.append({"url": job_url, "id": job_id})
                        else:
                            logger.debug("Could not extract URL from job element")
                    except Exception as e:
                        logger.warning(f"Error parsing job element: {e}")

                if selector_vacancies:
                    vacancies.extend(selector_vacancies)
                    logger.info(
                        f"Found {len(selector_vacancies)} job elements using selector: {selector}"
                    )
                    break

            # If no jobs found on first page, log warning
            if self.page_num == 0 and len(vacancies) == 0:
                logger.warning("No job listings found on LinkedIn search page")

            logger.info(
                f"Successfully parsed {len(vacancies)} job vacancies from page {self.page_num}"
            )
            self.total_discovered_jobs += len(vacancies)
            emit_event(
                "jobs_discovered",
                f"Found {len(vacancies)} jobs on page {self.page_num}",
                count=len(vacancies),
                total_discovered=self.total_discovered_jobs,
                page_num=self.page_num,
            )

        except Exception as e:
            logger.error(f"Error parsing job vacancies from page {self.page_num}: {e}")
            await debug_capture(self.page, "vacancies_parse_error")
            # Return empty list on error to continue processing
            return []

        return vacancies

    async def _is_applied_job_card(self, job_element: Any) -> bool:
        """Return True when the search result card is marked as already applied."""
        selectors = [
            ".job-card-container__footer-job-state",
            ".job-card-container__footer-wrapper",
            "li",
        ]
        for selector in selectors:
            try:
                locator = job_element.locator(selector)
                if isawaitable(locator):
                    continue
                count = await locator.count()
                for index in range(count):
                    text = (await locator.nth(index).inner_text() or "").strip().lower()
                    if text == "applied":
                        return True
            except Exception:
                continue

        try:
            text = (await get_clean_text(job_element)).lower()
            return any(line.strip() == "applied" for line in text.splitlines())
        except Exception:
            return False

    async def start_applying(self) -> None:
        """Send applications to all employers on all pages (async)"""
        # define the start time of the search
        if self.cache.last_run:
            last_run = self.cache.get_last_run_datetime()
            # if this is not the first launch - increase the time of the last search by 24 hours
            # and write it as the last search (to avoid the drift of the start time of the program)
            self.cache.last_run = (last_run + timedelta(hours=24)).isoformat()
        else:
            self.cache.update_last_run()
        result = ""
        # write recommendations for improving the resume
        self.resume_improvement_recommendations()
        seen_page_signatures = set()
        # continue until the maximum number of applications is reached
        while self.success_applies_num < self.max_applies_num and self.applies_num < 400:
            # Check if execution is paused
            if self.pause_checker:
                await self.pause_checker()

            # go through all pages until they are finished
            vacancies = await self.get_vacancies_from_page()
            if len(vacancies) == 0:
                if self.page_num == 1:
                    logger.warning("No vacancies found for the search query")
                break

            page_signature = tuple(vacancy.get("id") or vacancy.get("url") for vacancy in vacancies)
            if page_signature in seen_page_signatures:
                logger.info("Detected repeated LinkedIn result page; stopping pagination")
                break
            seen_page_signatures.add(page_signature)

            for vacancy in vacancies:
                # Check if execution is paused before processing each job
                if self.pause_checker:
                    await self.pause_checker()

                # Stop starting new jobs once a shutdown has been requested
                if runtime_controller.shutdown_state == ShutdownState.DRAINING:
                    logger.info("Shutdown requested — stopping before the next job")
                    result = "Shutdown"
                    break

                url = vacancy.get("url")
                try:
                    result = await self.apply_job(vacancy)
                    if result == "Limit":
                        logger.warning("Maximum number of applications reached")
                        break
                except StopRequested:
                    raise
                except Exception as e:
                    if self._is_target_closed_error(e):
                        logger.warning("Browser was closed during job processing; stopping run")
                        result = "Error"
                        break
                    tb_str = traceback.format_exc()
                    logger.error(f"Unknown error on the page: {url}\n{tb_str}")
                    await debug_capture(self.page, "apply_loop_error")
                    # counter of repeated errors, if too many errors in a row -
                    # exit the program and send a notification
                    if self.error_num == MAX_APPLIES_NUM:
                        logger.error(f"Critical number of consecutive errors {MAX_APPLIES_NUM}")
                        result = "Error"
                        break
                    else:
                        self.error_num += 1
                    continue
                else:
                    self.error_num = 0
            # break the search for vacancies if the limit is reached
            if result == "Limit" or result == "Error" or result == "Shutdown":
                break
            # go to the next page
            if not await self._go_to_next_page():
                logger.info("No further result pages available")
                break
        logger.info(f"Applications sent: {self.success_applies_num}")
        logger.info("Ending the work.")
        await self.send_report(result)

    async def apply_job(self, vacancy: Dict[str, Any]) -> str:
        """Send applications to all employers on the page (async)"""
        minimum_job_time = time.time() + MINIMUM_WAIT_TIME_SEC
        evaluation = {"interest_score": None, "interest_reason": None, "skills": None}
        # Open vacancy in a new window/tab
        original_page = self.page
        new_page = await self.page.context.new_page()
        self.page = new_page
        # Navigate to job page
        try:
            await new_page.goto(vacancy["url"], wait_until="domcontentloaded")
            logger.info(f"Navigated to job URL: {vacancy['url']}")
            await async_pause(3, 4)

            # scrape the vacancy
            job = await self._get_detailed_job_description()
            company_name = job.company_name
            company_job_title = job.job_title
            logger.info(f"Found a vacancy {company_job_title}")
            # if the vacancy has not been seen yet and the company is not in the blacklist
            # - start the process of applying to the vacancy
            if not job.is_valid_for_application():
                reason = "Job is not valid for application. Reason: "
                if not job.job_title:
                    reason += "Job is empty\n"
                elif not job.company_name:
                    reason += "Company name is empty\n"
                elif not job.url:
                    reason += "URL is empty\n"
                if not job.job_description:
                    reason += "Job description is empty\n"
                apply_result = "Skip", reason
                logger.warning(f"Job is not valid for application, skipping:\n{reason}")
                await async_pause(1, 2)
                await self._handle_apply_result(apply_result, job)
                return "Skip"

            if self._is_blacklisted(sanitize_text(company_name)):
                apply_result = "Skip", "Vacancy in the blacklist"
                logger.warning("Vacancy in the blacklist, skipping")
                await async_pause(1, 2)
                await self._handle_apply_result(apply_result, job)
                return "Skip"

            is_seen, reason = self._job_is_already_seen(job)
            if is_seen:
                apply_result = "Skip", reason
                logger.warning(f"Skipping the vacancy for the reason: {reason}")
                await async_pause(1, 2)
            else:
                if MONKEY_MODE is True and COLLECT_INFO_MODE is False:
                    # in 'monkey mode' any vacancy is considered interesting
                    job_is_interesting = True
                    score = 0
                    reasoning = "Monkey mode"
                    logger.info(
                        "Monkey mode is enabled and Collect info mode is disabled, applying to all vacancies"
                    )
                else:
                    (
                        job_is_interesting,
                        score,
                        reasoning,
                    ) = self.llm_answerer_component.job_is_interesting(job.model_dump())
                evaluation["interest_score"] = int(score) if str(score).isdigit() else 0
                evaluation["interest_reason"] = reasoning
                if not job_is_interesting:
                    logger.info(
                        f"Skipping uninteresting job: {job.job_title} at {job.company_name}"
                    )
                    await self._handle_apply_result(("Skip", reasoning), job, evaluation=evaluation)
                    return "Skip"
                # update the list of required skills for the vacancy and save job info to file
                # only if the vacancy was scored and considered interesting
                if int(score) > 0:
                    # extract skills from the vacancy
                    job.skills = self._extract_skills_from_vacancy(job)
                    evaluation["skills"] = self.job_key_skills
                    self._update_skill_stat(self.job_key_skills)
                    # set the vacancy to answerer
                    if COLLECT_INFO_MODE is True:
                        self._save_interesting_job(job, score, reasoning)

                if COLLECT_INFO_MODE:
                    logger.info(
                        "We are in the mode of collecting skill statistics or searching for "
                        "interesting jobs - do not apply to the vacancy"
                    )
                    return "Ok"

                self.llm_answerer_component.set_job(job.model_dump())
                self.submitted_resume_path = None
                self.already_applied_at = None
                self.already_applied_at_text = None

                if EASY_APPLY_ONLY_MODE is False:
                    apply_url = await self._check_apply_button()
                    if apply_url:
                        if TEST_MODE:
                            apply_result = "Skip", "Test mode"
                        elif any(host in apply_url for host in EXTERNAL_APPLY_SKIP_ATSES):
                            logger.info(f"Skipping unsupported external ATS: {apply_url}")
                            apply_result = "Skip", f"Unsupported external ATS: {apply_url}"
                        else:
                            apply_result = await self.llm_agent_component.apply_to_job(apply_url)
                    else:
                        apply_result = await self.easy_apply(job)
                else:
                    apply_result = await self.easy_apply(job)
                if self.submitted_resume_path:
                    evaluation["submitted_resume_path"] = self.submitted_resume_path
                if self.already_applied_at:
                    evaluation["applied_at"] = self.already_applied_at
                if self.already_applied_at_text:
                    evaluation["applied_at_text"] = self.already_applied_at_text
                # if the vacancy is skipped for the reason of missing information, add it to the list of vacancies,
                # information about which will then be sent to the client
                result, reason = apply_result
                if result == "Skip" and reason.startswith("Could not"):
                    self._collect_job_info(company_job_title, company_name, job.url, reason)
            result, _ = apply_result
            await self._handle_apply_result(apply_result, job, evaluation=evaluation)
            if self.success_applies_num >= self.max_applies_num:
                logger.info(
                    f"The maximum number of applications has been reached: "
                    f"{self.success_applies_num}/{self.max_applies_num}"
                )
                return "Limit"
            return result
        finally:
            # if the page was processed faster than the minimum time -
            # wait until this time is over
            time_left = int(minimum_job_time - time.time())
            if time_left > 0:
                await async_pause(time_left, time_left + 5)
            try:
                await new_page.close()
            except Exception as e:
                if not self._is_target_closed_error(e):
                    logger.warning(f"Failed to close job page: {e}")
            self.page = original_page
            try:
                await self.page.bring_to_front()
            except Exception as e:
                if self._is_target_closed_error(e):
                    logger.warning("Browser was closed before returning to the search page")
                else:
                    raise

    async def easy_apply(self, job: Job) -> Tuple[str, str]:
        """Apply to the vacancy using LinkedIn Easy Apply functionality (async)"""
        easy_applier_component = LinkedInEasyApplier(
            self.page,
            self.llm_answerer_component,
            self.resume_anonymizer,
            self.resume_generator_manager,
            self.pause_checker,
            Path(OUTPUT_DIR_LINKEDIN) / "answers.yaml",
            RESUME_DIR,
            COVER_LETTER_DIR,
            TEST_MODE,
        )
        easy_applier_component.set_page(self.page)
        apply_result, self.submitted_resume_path = await easy_applier_component.apply_to_job(job)
        applied_at = getattr(easy_applier_component, "already_applied_at", None)
        applied_at_text = getattr(easy_applier_component, "already_applied_at_text", None)
        self.already_applied_at = applied_at if isinstance(applied_at, str) else None
        self.already_applied_at_text = applied_at_text if isinstance(applied_at_text, str) else None
        return apply_result

    async def _scroll_to_load_jobs(self):
        """Scroll the job results container to load all job listings (async)"""
        scrollable_elements = []

        async def _get_children(element, current_depth: int = 0, max_depth: int = 3) -> None:
            """Get all children of the element (Playwright Locator-aware) - async."""
            if current_depth > max_depth:
                return
            try:
                # Use Playwright locator scoping for child selection
                if hasattr(element, "locator"):
                    child_locator = element.locator(":scope > *")
                    count = await child_locator.count()
                    for i in range(count):
                        child = child_locator.nth(i)
                        try:
                            if await is_scrollable(child):
                                scrollable_elements.append(child)
                            else:
                                await _get_children(child, current_depth + 1, max_depth)
                        except Exception:
                            continue
            except Exception:
                pass

        try:
            # Find the LinkedIn job results container using safe methods
            job_container = None
            container_selectors = [
                ".scaffold-layout__list",
                ".scaffold-layout__list-container",
                "[data-job-id]",
                ".jobs-search-results-list",
                ".jobs-search-results__list",
                ".jobs-search-results__list-container",
                ".jobs-search-results",
            ]

            for selector in container_selectors:
                job_container = await find_element_safely(self.page, selector, "css selector")
                if job_container:
                    logger.debug(f"Found job container with selector: {selector}")
                    break
            else:
                logger.debug("Could not find job container with selector: {selector}")
                return

            # Try to scroll all scrollable elements
            await _get_children(job_container)

            for element in scrollable_elements:
                try:
                    # Scroll to bottom, then back to top to load all content
                    if await scroll_slowly(element, "down"):
                        await async_pause(0.2, 0.3)
                        await scroll_slowly(element, "up")
                except Exception as e:
                    logger.debug(f"Element scrolling failed: {e}")

        except Exception as e:
            logger.warning(f"Error during job container scrolling: {e}")
            await debug_capture(self.page, "scroll_jobs_error")

    @staticmethod
    def _canonical_job_url_from_id(job_id: str) -> str:
        return f"https://www.linkedin.com/jobs/view/{job_id}"

    @staticmethod
    def _normalize_job_url(href: str) -> str | None:
        if not href:
            return None

        current_job_match = re.search(r"[?&]currentJobId=(\d+)", href)
        if current_job_match:
            return LinkedInJobManager._canonical_job_url_from_id(current_job_match.group(1))

        view_match = re.search(r"/jobs/view/(\d+)", href)
        if view_match:
            if href.startswith("https://www.linkedin.com") or href.startswith(
                "https://linkedin.com"
            ):
                return href
            if not href.startswith("http"):
                return f"https://www.linkedin.com{href}"

        return None

    async def _get_direct_data_job_id(self, job_element) -> str:
        for attr in ("data-occludable-job-id", "data-job-id"):
            try:
                job_id = await job_element.get_attribute(attr) or ""
                if isinstance(job_id, str) and job_id.isdigit():
                    return job_id
            except Exception:
                pass
        return ""

    async def _extract_job_url(self, job_element) -> str | None:
        """Extract job URL from job element using multiple selector strategies (async)"""
        logger.debug("Extracting job URL from element")

        # Check direct job ID attributes first (avoids child element queries)
        job_id = await self._get_direct_data_job_id(job_element)
        if job_id:
            return self._canonical_job_url_from_id(job_id)

        # Try different selectors for job links
        link_selectors = [
            "a[href*='currentJobId=']",
            "a[href*='/jobs/collections/recommended']",
            "a[href*='/jobs/collections/top-applicant']",
            "a[href*='/jobs/view/']",
            "a[data-control-name='job_card_title']",
            ".job-card-job-posting-card-wrapper__card-link",
            ".base-card__full-link",
            ".job-card-container__link",
            ".jobs-search-results__list-item-action",
        ]

        for selector in link_selectors:
            try:
                href = await get_element_attribute_safely(job_element, selector, "href")
                job_url = self._normalize_job_url(href)
                if job_url:
                    return job_url
            except Exception:
                continue

        return None

    async def _get_detailed_job_description(self) -> Job:
        """Get detailed job description by extracting specific sections from the job page (async)"""
        job = Job()

        # Extract job ID and set URL from current URL - framework agnostic
        try:
            current_url = self.page.url
            if "/jobs/view/" in current_url:
                match = re.search(r"/jobs/view/(\d+)", current_url)
                if match:
                    job.job_id = match.group(1)
                job.url = current_url
        except Exception as e:
            logger.warning(f"Could not extract URL information: {e}")

        try:
            job.job_title = await self._extract_job_title()
            job.company_name = await self._extract_company_name()
            job.job_description = await self._extract_job_description()
            job.company_description = await self._extract_company_description()
            # job.recruiter_link = await self._get_job_recruiter()

        except Exception as e:
            logger.warning(f"Could not get detailed job description: {e}")
            await debug_capture(self.page, "job_description_error")

        return job

    async def _extract_company_name(self) -> str:
        """Extract company name from the job page using multiple selector strategies (async)"""
        xpath_selectors = [
            # New LinkedIn UI: find a elements with company link pattern
            "//a[contains(@href, '/company/')]",
        ]

        for xpath_selector in xpath_selectors:
            elements = await find_elements_safely(self.page, xpath_selector, "xpath")
            for element in elements:
                try:
                    text = await get_clean_text(element)
                    if text:
                        text = text.strip()
                        if text and len(text) > 1:  # Ensure it's a meaningful company name
                            logger.debug(
                                f"Found company name '{text}' using xpath: {xpath_selector}"
                            )
                            return text
                except Exception:
                    continue

        # Fallback: extract from "Set alert for similar jobs" paragraph
        # Format: "Job Title, Company Name, State, Country"
        alert_xpath = (
            "//h2[contains(text(), 'Set alert for similar jobs')]/following-sibling::div[1]//p"
        )
        elements = await find_elements_safely(self.page, alert_xpath, "xpath")
        for element in elements:
            try:
                text = await get_clean_text(element)
                if text:
                    parts = [p.strip() for p in text.split(",")]
                    if len(parts) >= 2 and parts[1]:
                        logger.debug(f"Found company name '{parts[1]}' from alert section")
                        return parts[1]
            except Exception:
                continue

        logger.debug("Could not extract company name from job page")
        return None

    async def _extract_job_title(self) -> str:
        """Extract job title from the job page using multiple selector strategies (async)"""
        xpath_selectors = [
            # New LinkedIn UI: find "Set alert for similar jobs" heading, then the job title in the following paragraph
            "//h2[contains(text(), 'This job alert is on')]/parent::div/following-sibling::div[1]/p",
            "//h2[contains(text(), 'Set alert for similar jobs')]/following-sibling::div[1]/p",
        ]

        for xpath_selector in xpath_selectors:
            elements = await find_elements_safely(self.page, xpath_selector, "xpath")
            for element in elements:
                try:
                    text = await get_clean_text(element)
                    if text:
                        # Clean up the text - take first line and strip
                        text = text.strip().split("\n")[0].strip()

                        # Handle "Job Title, Location" format - extract only job title
                        if ", " in text and len(text.split(", ")) >= 2:
                            # Extract job title (first part before comma)
                            job_title = text.split(",")[0].strip()
                            if job_title and len(job_title) > 3:
                                logger.debug(
                                    f"Found job title '{job_title}' (extracted from '{text}') using xpath: {xpath_selector}"
                                )
                                return job_title
                        elif text and len(text) > 3:  # Ensure it's a meaningful title
                            logger.debug(f"Found job title '{text}' using xpath: {xpath_selector}")
                            return text
                except Exception:
                    continue

        logger.debug("Could not extract job title from job page")
        return None

    async def _extract_job_description(self) -> str:
        """Extract "About the job" section using multiple selector strategies (async)"""
        about_job_selectors = [
            # Try to find element after "About the job" heading
            (
                "//h2[contains(text(), 'About the job')]/following::p[1]//span[@data-testid='expandable-text-box']",
                "xpath",
            ),
            ("//h2[contains(text(), 'About the job')]/following::p[1]", "xpath"),
        ]

        job_description = None
        for selector, by in about_job_selectors:
            try:
                if by == "xpath":
                    element = await find_element_safely(self.page, selector, by)
                    if element:
                        job_description = await get_clean_text(element)
                else:
                    job_description = await get_element_text(self.page, selector)

                if job_description:
                    logger.debug(f"Found job description using selector: {selector}")
                    # Clean up the text
                    job_description = job_description.strip()
                    if len(job_description) > 50:  # Ensure it's substantial content
                        break
            except Exception as e:
                logger.debug(f"Selector '{selector}' failed: {e}")
                continue

        if not job_description:
            logger.debug("Could not extract job description from job page")
            return None

        # Also extract "Requirements added by the job poster" section
        requirements_text = await self._extract_requirements_section()
        if requirements_text:
            job_description = f"{job_description}\n\n{requirements_text}"

        return job_description

    async def _extract_requirements_section(self) -> str:
        """Extract "Requirements added by the job poster" section (async)"""
        try:
            requirements_parts = []

            # Get all requirement paragraphs after the "Requirements added by the job poster" heading
            requirements_xpath = (
                "//p[contains(text(), 'Requirements added by the job poster')]/following-sibling::p"
            )
            requirement_elements = await find_elements_safely(
                self.page, requirements_xpath, "xpath"
            )

            if requirement_elements:
                for element in requirement_elements:
                    try:
                        text = await get_clean_text(element)
                        if text and text.strip():
                            # Stop if we hit a horizontal rule or another section
                            # Check if this element is before an <hr> or another heading
                            text = text.strip()
                            if text.startswith("•") or text.startswith("-"):
                                requirements_parts.append(text)
                            else:
                                # Might be the end of requirements section
                                break
                    except Exception:
                        continue

            if requirements_parts:
                requirements_text = "Requirements added by the job poster\n\n" + "\n".join(
                    requirements_parts
                )
                logger.debug("Found requirements section")
                return requirements_text

        except Exception as e:
            logger.debug(f"Could not extract requirements section: {e}")

        return None

    async def _extract_company_description(self) -> str:
        """Extract company description from the job page (async)"""
        company_description = None
        about_company_selectors = [
            # More specific: Find expandable text box that comes after "About the company" but before next major section
            (
                "//h2[contains(text(), 'About the company')]/following::span[@data-testid='expandable-text-box'][not(ancestor::h2[contains(text(), 'About the job')])][1]",
                "xpath",
            ),
        ]

        for selector, by in about_company_selectors:
            try:
                if by == "xpath":
                    element = await find_element_safely(self.page, selector, by)
                    if element:
                        element_text = await get_clean_text(element)
                    else:
                        element_text = None
                else:
                    element_text = await get_element_text(self.page, selector)

                if element_text:
                    # Clean up the text - remove "more" button text if present
                    element_text = element_text.strip()
                    # Remove the "… more" button text that might be at the end
                    element_text = re.sub(r"\s*…\s*more\s*$", "", element_text, flags=re.IGNORECASE)
                    element_text = element_text.strip()

                    if len(element_text) > 20:  # Ensure it's substantial content
                        # Split by newlines and join, but keep meaningful structure
                        element_list = element_text.split("\n")
                        if len(element_list) > 1:
                            # Join lines but preserve paragraphs (double newlines)
                            company_description = "\n".join(element_list)
                        else:
                            company_description = element_text
                        logger.debug(f"Found company description using selector: {selector}")
                        return company_description
            except Exception as e:
                logger.debug(f"Selector '{selector}' failed: {e}")
                continue

        logger.debug("Could not extract company description from job page")
        return None

    async def _get_job_recruiter(self):
        """Get job recruiter information (async)"""
        logger.debug("Getting job recruiter information")
        try:
            recruiter = self.page.locator(
                "xpath=//h2[text()=\"Meet the hiring team\" or contains(text(), 'Meet the hiring team')]/following::a[contains(@href, 'linkedin.com/in/')]"
            ).first
            if await recruiter.count() > 0:
                recruiter_link = await recruiter.get_attribute("href") or ""
                logger.debug(f"Job recruiter link retrieved successfully: {recruiter_link}")
                return recruiter_link
            logger.debug("No recruiter link found in the hiring team section")
            return ""
        except Exception:
            logger.warning("Failed to retrieve recruiter information")
            return ""

    async def _check_apply_button(self) -> str:
        """Check if the apply button is present and return the URL of the apply button (async).
        If no apply button is found, return an empty string."""
        easy_apply_selectors = ['//a[contains(@aria-label, "Easy Apply")]']
        for selector in easy_apply_selectors:
            easy_apply_buttons = await find_elements_safely(self.page, selector, "xpath")
            if len(easy_apply_buttons) > 0:
                return ""
        apply_selectors = [
            '//a[contains(., "Apply")]',
        ]
        for selector in apply_selectors:
            apply_buttons = await find_elements_safely(self.page, selector, "xpath")
            if len(apply_buttons) > 0:
                return await self._get_button_link(apply_buttons)
        return None

    async def _get_button_link(self, apply_buttons: List[Any]) -> str:
        """Get the link of the button (Playwright context) - async."""
        for button in apply_buttons:
            try:
                if not (await button.is_visible() and await button.is_enabled()):
                    logger.debug("Apply button is not visible or enabled")
                    continue
                async with self.page.context.expect_page() as new_page_info:
                    logger.debug("Clicking apply button")
                    await button.first.click(timeout=1000)
                    # Handle "Job search safety reminder" dialog if it appears
                    await async_pause()
                    continue_btn = await find_element_safely(
                        self.page,
                        '//*[contains(., "Continue applying") and (self::button or self::a)]',
                        "xpath",
                    )
                    if continue_btn:
                        logger.debug(
                            "Safety reminder dialog detected, clicking 'Continue applying'"
                        )
                        await continue_btn.click(timeout=1000)
                        await async_pause()
                new_page = await new_page_info.value
                await async_pause()
                link = new_page.url
                await async_pause()
                await new_page.close()
                logger.debug(f"Apply button link is obtained successfully: {link}")
                return link
            except Exception as e:
                logger.debug(f"Failed to get the link of the apply button: {e}")
        logger.warning("No apply button found")
        return ""

    async def _go_to_next_page(self) -> bool:
        """Go to the next page using framework-agnostic methods (async)"""
        target_page_label = self.page_num + 2  # page_num is 0-indexed; LinkedIn labels pages from 1
        logger.info(f"Going to the page {target_page_label}")
        emit_event(
            "page_changed", f"Moving to page {target_page_label}", page_num=target_page_label
        )

        # Try multiple selectors for next page button
        next_page_selectors = [
            f"button[aria-label='Page {target_page_label}']:not([disabled]):not([aria-current='page'])",
            f"//button[@aria-label='Page {target_page_label}' and not(@disabled) and not(@aria-current='page')]",
            f"//button[contains(@aria-label, 'Page {target_page_label}') and not(@disabled) and not(@aria-current='page')]",
            "button[aria-label='View next page']:not([disabled])",
            "//button[@aria-label='View next page' and not(@disabled)]",
            "//button[contains(@aria-label, 'next') and not(@disabled)]",
            "//button[contains(@aria-label, 'Next') and not(@disabled)]",
            "button[aria-label*='Next']:not([disabled])",
            "button[aria-label*='next']:not([disabled])",
            ".jobs-search-results-list__pagination button[aria-label*='next']:not([disabled])",
            "button.artdeco-pagination__button--next:not([disabled])",
        ]

        page_clicked = False
        for selector in next_page_selectors:
            if await safe_click(self.page, selector, timeout=10000):
                logger.debug(f"Clicked next page using selector: {selector}")
                page_clicked = True
                break

        if not page_clicked:
            # Fallback - try to find element first, then click
            for selector in next_page_selectors:
                by = "xpath" if selector.startswith("//") else "css selector"
                element = await find_element_safely(self.page, selector, by)
                if element:
                    try:
                        await element.click(timeout=1000)
                        logger.debug(f"Clicked next page element using selector: {selector}")
                        page_clicked = True
                        break
                    except Exception as e:
                        logger.debug(f"Failed to click next page element: {e}")
                        continue

        if not page_clicked:
            logger.warning("Could not find or click next page button")
            return False

        self.page_num += 1
        await async_pause(2, 3)
        return True


if __name__ == "__main__":
    """Test script to verify Playwright scrolling functionality"""
    import asyncio

    from src.utils.browser_utils import create_playwright_browser

    async def test_linkedin_job_extraction():
        """Test finding job elements and extracting URLs from LinkedIn jobs page (async)"""
        print("🚀 Starting LinkedIn job extraction test...")

        async def extract_job_url_from_element(job_element):
            """Extract job URL from job element using multiple selector strategies (async)"""
            print(f"🔍 Extracting job URL from element type: {type(job_element)}")
            # Try different selectors for job links
            link_selectors = [
                "a[href*='/jobs/view/']",
                "a[data-control-name='job_card_title']",
                ".base-card__full-link",
                ".job-card-container__link",
                ".jobs-search-results__list-item-action",
            ]

            for selector in link_selectors:
                try:
                    href = await get_element_attribute_safely(job_element, selector, "href")
                    if href and "/jobs/view/" in href:
                        print(f"✅ Found job URL using selector '{selector}': {href}")
                        return href
                except Exception as e:
                    print(f"⚠️ Failed with selector '{selector}': {e}")
                    continue

            print("❌ Could not extract job URL from element")
            return None

        try:
            # Create Playwright browser instance (async)
            browser, context, page = await create_playwright_browser()
            print("✅ Browser created successfully (async)")

            # Navigate to LinkedIn jobs search
            print("🔗 Navigating to LinkedIn jobs search...")
            await page.goto("https://linkedin.com/jobs/search")
            print("✅ Page loaded")

            # Wait a bit for dynamic content to load
            await async_pause(5, 6)

            # Find all job listing elements using multiple selectors
            print("🔍 Looking for job elements...")
            job_selectors = [
                "//*[starts-with(@class, 'flex-grow-1')]",
                "div[data-job-id]",
                ".jobs-search-results__list-item",
                ".job-card-container",
                ".base-card",
                ".job-card-list__entity-lockup",
                ".scaffold-layout__list-item",
            ]

            job_elements = []
            for selector in job_selectors:
                print(f"🔍 Trying selector: {selector}")
                try:
                    if selector.startswith("//"):
                        # XPath selector
                        elements = await page.locator("xpath=" + selector).all()
                    else:
                        # CSS selector
                        elements = await page.locator(selector).all()

                    if elements:
                        job_elements = elements
                        print(f"✅ Found {len(elements)} job elements using selector: {selector}")
                        break
                except Exception as e:
                    print(f"⚠️ Selector '{selector}' failed: {e}")
                    continue

            if not job_elements:
                print("❌ No job elements found!")
                # Debug: show what elements are available
                all_elements = await page.locator("*").all()
                print(f"📋 Total elements on page: {len(all_elements)}")

                # Show elements with job-related classes
                job_related = await page.locator("[class*='job']").all()
                print(f"📋 Elements with 'job' in class: {len(job_related)}")
                return

            print(f"🎯 Processing {len(job_elements)} job elements...")

            # Extract URLs from each job element
            extracted_urls = []
            for i, job_element in enumerate(job_elements[:5]):  # Test first 5 elements
                print(f"\n📝 Processing job element {i + 1}/{min(5, len(job_elements))}...")
                job_url = await extract_job_url_from_element(job_element)
                if job_url:
                    extracted_urls.append(job_url)
                    # Extract job ID from URL
                    match = re.search(r"/jobs/view/(\d+)", job_url)
                    job_id = match.group(1) if match else "unknown"
                    print(f"✅ Job {i + 1} - ID: {job_id}")
                else:
                    print(f"❌ Job {i + 1} - No URL found")

            # Summary
            print("\n📊 SUMMARY:")
            print(f"Total job elements found: {len(job_elements)}")
            print(f"URLs successfully extracted: {len(extracted_urls)}")
            print(f"Success rate: {len(extracted_urls) / min(5, len(job_elements)) * 100:.1f}%")

            if extracted_urls:
                print("\n🔗 Sample URLs:")
                for i, url in enumerate(extracted_urls[:3]):
                    print(f"  {i + 1}. {url}")

                first_url = extracted_urls[0]
                first_url = "https://linkedin.com" + "/".join(first_url.split("/")[:4])

                print(f"\n🔗 Navigating to first job URL: {first_url}")
                await page.goto(first_url)
                print("✅ Page loaded")
                await async_pause(3, 4)

                # Create LinkedInJobManager instance with dummy dependencies to test extraction
                print("🔍 Extracting detailed job description...")
                # We can pass None for dependencies that aren't used in _get_detailed_job_description
                applier = LinkedInJobManager(page, "", None, None)

                job = await applier._get_detailed_job_description()

                print("\n📊 JOB DETAILS EXTRACTED:")
                print(f"Job Title: {job.job_title}")
                print(f"Company Name: {job.company_name}")
                desc_len = len(job.job_description) if job.job_description else 0
                print(f"Job Description: {desc_len} chars")
                comp_desc_len = len(job.company_description) if job.company_description else 0
                print(f"Company Description: {comp_desc_len} chars")

                # Validation
                missing_fields = []
                if not job.job_title:
                    missing_fields.append("job_title")
                if not job.company_name:
                    missing_fields.append("company_name")
                if not job.job_description:
                    missing_fields.append("job_description")
                if not job.company_description:
                    missing_fields.append("company_description")

                if missing_fields:
                    print(f"❌ VALIDATION FAILED. Missing fields: {', '.join(missing_fields)}")
                else:
                    print("✅ VALIDATION PASSED: All required fields extracted successfully.")

            # Keep browser open for a moment to see results
            print("\n⏳ Keeping browser open for 10 seconds to observe results...")
            await async_pause(10, 11)

        except Exception as e:
            print(f"❌ Test failed with error: {e}")
            import traceback

            traceback.print_exc()

        finally:
            try:
                # Clean up (async)
                await context.close()
                await browser.close()
                print("✅ Browser closed successfully")
            except Exception:
                pass

    # Run the async test
    asyncio.run(test_linkedin_job_extraction())
