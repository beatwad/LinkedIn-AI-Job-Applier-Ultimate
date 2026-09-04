import time
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Any, List, Tuple

from playwright.sync_api import Page

from config.app_config import (
    COLLECT_INFO_MODE,
    EASY_APPLY_ONLY_MODE,
    MAX_APPLIES_NUM,
    MINIMUM_WAIT_TIME_SEC,
    MONKEY_MODE,
    TEST_MODE,
)
from config.constants import COVER_LETTER_DIR, OUTPUT_DIR_INDEED, RESUME_DIR, SEARCH_CONFIG_FILE
from config.logger_config import logger
from src.dashboard.runtime import StopRequested, emit_event
from src.job_manager.indeed import indeed_base_url
from src.job_manager.indeed.easy_applier_indeed import IndeedEasyApplier
from src.job_manager.job_manager import BaseJobManager
from src.pydantic_models.job_models import Job
from src.utils.browser_utils import (
    debug_capture,
    find_element_safely,
    find_elements_safely,
    safe_click,
)
from src.utils.runtime_control import ShutdownState, runtime_controller
from src.utils.utils import async_pause, load_yaml_file, sanitize_text

search_config = load_yaml_file(SEARCH_CONFIG_FILE)
logger.info(f"Maximum allowed number of applications: {MAX_APPLIES_NUM}")

INDEED_JOB_CARD_SELECTOR = "div.job_seen_beacon, div[data-testid='jobcard-wrapper']"
INDEED_JOB_TITLE_SELECTOR = "h2.jobTitle a, [data-testid='jobTitle'] a"
INDEED_COMPANY_SELECTOR = "[data-testid='company-name'], .companyName"
INDEED_LOCATION_SELECTOR = "[data-testid='text-location'], .companyLocation"
INDEED_EASY_APPLY_BADGE = "span.iaLabel, [data-testid='ia-badge']"
INDEED_APPLY_BUTTON = (
    "span.indeed-apply-status-not-applied button, "
    "button[aria-label*='Apply with Indeed'], "
    "button[aria-label*='Indeed Apply'], "
    "#indeedApplyButton, "
    "[data-testid='indeedApplyButton-test'], "
    ".jobsearch-IndeedApplyButton-buttonWrapper"
)
INDEED_NEXT_PAGE_SELECTOR = (
    "a[data-testid='pagination-page-next'], nav[role='navigation'] a[aria-label='Next Page']"
)


class IndeedJobManager(BaseJobManager):
    """Class for searching and sending applications to employers on Indeed"""

    def __init__(
        self, page: Page, linkedin_email: str, resume_anonymizer: Any, search_component: Any
    ):
        logger.info("Initializing IndeedJobManager")
        self.page = page
        self.email = linkedin_email  # reuses the same parameter name for interface compatibility
        self.resume_anonymizer = resume_anonymizer
        self.search_component = search_component
        self.llm_answerer_component = None
        self.llm_agent_component = None
        self.resume_generator_manager = None
        self.pause_checker = None
        self.jobs_no_info: List[Any] = []
        self.job_key_skills: List[str] = []
        self.interesting_jobs: List[Any] = []
        self.page_num = 0
        self.total_discovered_jobs = 0
        self.error_num = 0
        self.total_applies_num = 0
        self.applies_num = 0
        self.success_applies_num = 0
        self.resume_recommendations = ""
        self.submitted_resume_path = None

        logger.info("IndeedJobManager successfully initialized")

    # ------------------------------------------------------------------
    # Interface methods (same signatures as LinkedIn LinkedInJobManager)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Main application loop
    # ------------------------------------------------------------------

    async def start_applying(self) -> None:
        """Main loop: iterate over all search URLs and apply to jobs"""
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

        # for url in search_urls:
        self.page_num = 0
        await async_pause(1, 2)

        # continue until the maximum number of applications is reached
        while self.success_applies_num < self.max_applies_num and self.applies_num < 400:
            # Check if execution is paused
            if self.pause_checker:
                await self.pause_checker()

            # go through all pages until they are finished
            vacancies = await self.get_vacancies_from_page()
            if len(vacancies) == 0:
                if self.page_num == 0:
                    logger.warning("No vacancies found for the search query")
                # An empty location must not end the run while other configured
                # locations are still unsearched
                if await self._go_to_next_search():
                    continue
                break
            for vacancy in vacancies:
                # Check if execution is paused before processing each job
                if self.pause_checker:
                    await self.pause_checker()

                # Stop starting new jobs once a shutdown has been requested
                if runtime_controller.shutdown_state == ShutdownState.DRAINING:
                    logger.info("Shutdown requested — stopping before the next job")
                    result = "Shutdown"
                    break

                try:
                    result = await self.apply_job(vacancy)
                    if result == "Limit":
                        logger.warning("Maximum number of applications reached")
                        break
                except StopRequested:
                    raise
                except Exception:
                    tb_str = traceback.format_exc()
                    logger.error(f"Unknown error on the page: {self.page.url}\n{tb_str}")
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
            # go to the next page; when the pages run out, move to the next
            # configured search (one per location) before giving up
            if not await self._go_to_next_page():
                if not await self._go_to_next_search():
                    break

        # if result == "Limit" or result == "Error":
        #     break

        logger.info(f"Applications sent: {self.success_applies_num}")
        logger.info("Ending the work.")
        await self.send_report(result)

    async def _go_to_next_search(self) -> bool:
        """Move to the next configured search URL. False when all are exhausted."""
        go_to_next_search = getattr(self.search_component, "go_to_next_search", None)
        if go_to_next_search is None:
            return False
        try:
            if not await go_to_next_search():
                return False
        except Exception as e:
            logger.warning(f"Could not start the next search: {e}")
            await debug_capture(self.page, "next_search_error")
            return False
        self.page_num = 0
        emit_event("page_changed", "Starting the next configured search", page_num=self.page_num)
        return True

    async def get_vacancies_from_page(self) -> List[Any]:
        """Return all job card elements on the current page"""
        try:
            await self.page.wait_for_selector(INDEED_JOB_CARD_SELECTOR, timeout=15000)
            await self._scroll_left_panel()
            cards = await find_elements_safely(self.page, INDEED_JOB_CARD_SELECTOR)
            if not cards:
                return []
            # Indeed's slider DOM can render multiple div.job_seen_beacon elements for
            # the same job (compact card + pre-fetched detail view). Deduplicate by
            # data-jk so each job is only processed once.
            seen_jks: set = set()
            unique_cards = []
            for card in cards:
                title_el = await find_element_safely(card, INDEED_JOB_TITLE_SELECTOR, timeout=500)
                jk = (await title_el.get_attribute("data-jk") or "") if title_el else ""
                if jk:
                    if jk in seen_jks:
                        continue
                    seen_jks.add(jk)
                unique_cards.append(card)
            self.total_discovered_jobs += len(unique_cards)
            emit_event(
                "jobs_discovered",
                f"Found {len(unique_cards)} jobs on page {self.page_num}",
                count=len(unique_cards),
                total_discovered=self.total_discovered_jobs,
                page_num=self.page_num,
            )
            return unique_cards
        except Exception as e:
            logger.warning(f"Could not find job cards: {e}")
            await debug_capture(self.page, "vacancies_not_found")
            return []

    async def _scroll_left_panel(self) -> None:
        """Scroll the full page to trigger lazy-loading of job cards"""
        await self.page.evaluate(
            """
            () => new Promise((resolve) => {
                const distance = document.body.scrollHeight;
                const durationMs = 2000;
                const startTime = performance.now();
                function step(now) {
                    const progress = Math.min((now - startTime) / durationMs, 1);
                    window.scrollTo(0, distance * progress);
                    if (progress < 1) requestAnimationFrame(step);
                    else resolve();
                }
                requestAnimationFrame(step);
            })
            """
        )
        await async_pause(1, 2)
        await self.page.evaluate("() => window.scrollTo(0, 0)")

    async def apply_job(self, vacancy: Any) -> str:
        """Process a single Indeed job card"""
        evaluation = {"interest_score": None, "interest_reason": None, "skills": None}
        job = await self._extract_job_from_card(vacancy)
        if job is None:
            return "Skip"

        already_seen, reason = self._job_is_already_seen(job)
        if already_seen:
            logger.info(
                f"Skipping already seen job: {job.job_title} at {job.company_name} ({reason})"
            )
            await self._handle_apply_result(("Skip", reason), job, evaluation=evaluation)
            return "Skip"

        if self.search_component.is_job_blacklisted(job.job_title, job.company_name, job.location):
            logger.info(f"Skipping blacklisted job: {job.job_title} at {job.company_name}")
            await self._handle_apply_result(
                ("Skip", "Vacancy in the blacklist"), job, evaluation=evaluation
            )
            return "Skip"

        if job.apply_method != "easy_apply" and EASY_APPLY_ONLY_MODE and not COLLECT_INFO_MODE:
            logger.info(f"Skipping external apply job: {job.job_title} at {job.company_name}")
            await self._handle_apply_result(
                ("Skip", "External apply not allowed"), job, evaluation=evaluation
            )
            return "Skip"

        minimum_job_time = time.time() + MINIMUM_WAIT_TIME_SEC
        new_page = await self.page.context.new_page()
        try:
            await new_page.goto(job.url, wait_until="domcontentloaded")
            await async_pause(1, 2)
            job.job_description = await self._extract_job_description_from_page(new_page)
            job.company_description = await self._extract_company_description(new_page)

            if MONKEY_MODE is True and COLLECT_INFO_MODE is False:
                job_is_interesting = True
                score, reasoning = 0, "Monkey mode"
                logger.info(
                    "Monkey mode is enabled and Collect info mode is disabled, applying to all vacancies"
                )
            else:
                interest_result = self.llm_answerer_component.job_is_interesting(job.model_dump())
                if interest_result is None:
                    apply_result = ("Error", "Error while determining if job is interesting")
                    await self._handle_apply_result(apply_result, job, evaluation=evaluation)
                    return "Error"
                job_is_interesting, score, reasoning = interest_result

            evaluation["interest_score"] = int(score) if str(score).isdigit() else 0
            evaluation["interest_reason"] = reasoning

            if not job_is_interesting:
                logger.info(f"Skipping uninteresting job: {job.job_title} at {job.company_name}")
                await self._handle_apply_result(("Skip", reasoning), job, evaluation=evaluation)
                return "Skip"
            # update the list of required skills for the vacancy and save job info to file
            # only if the vacancy was scored and considered interesting
            if int(score) > 0:
                # extract skills from the vacancy
                job.skills = self._extract_skills_from_vacancy(job)
                self._update_skill_stat(self.job_key_skills)
                evaluation["skills"] = self.job_key_skills
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

            if not EASY_APPLY_ONLY_MODE and job.apply_method == "external":
                if TEST_MODE:
                    apply_result = "Skip", "Test mode"
                else:
                    apply_url = await self._get_button_link(new_page)
                    apply_result = await self.llm_agent_component.apply_to_job(apply_url)
            else:
                apply_result = await self.easy_apply(job, new_page)

            if self.submitted_resume_path:
                evaluation["submitted_resume_path"] = self.submitted_resume_path
            result, reason = apply_result
            if result == "Skip" and reason.startswith("Could not"):
                self._collect_job_info(job.job_title, job.company_name, job.url, reason)
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
                await async_pause(time_left, time_left + 1)
            await new_page.close()
            await self.page.bring_to_front()

    async def easy_apply(self, job: Job, page: Any = None) -> Tuple[str, str]:
        """Delegate application to IndeedEasyApplier"""
        easy_applier_component = IndeedEasyApplier(
            page=page,
            gpt_answerer=self.llm_answerer_component,
            resume_anonymizer=self.resume_anonymizer,
            resume_generator_manager=self.resume_generator_manager,
            pause_checker=self.pause_checker,
            answers_file=Path(OUTPUT_DIR_INDEED) / "answers.yaml",
            resume_dir=Path(RESUME_DIR),
            cover_letter_dir=Path(COVER_LETTER_DIR),
            test_mode=TEST_MODE,
        )
        apply_result, self.submitted_resume_path = await easy_applier_component.apply_to_job(job)
        return apply_result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _extract_job_from_card(self, card: Any) -> Job | None:
        """Extract job data from an Indeed job card element"""
        try:
            title_el = await find_element_safely(card, INDEED_JOB_TITLE_SELECTOR, timeout=3000)
            if not title_el:
                return None
            title = await title_el.text_content() or ""
            jk = await title_el.get_attribute("data-jk") or ""
            if "0123456789abcdef" in "".join(sorted(jk)):
                return None
            if jk:
                # Use the canonical viewjob URL so the same job always maps to the
                # same URL regardless of which slider item or tracking URL was found.
                job_url = f"{indeed_base_url()}/viewjob?jk={jk}"
            else:
                job_url_path = await title_el.get_attribute("href") or ""
                job_url = (
                    job_url_path
                    if job_url_path.startswith("http")
                    else f"{indeed_base_url()}{job_url_path}"
                )

            company_el = await find_element_safely(card, INDEED_COMPANY_SELECTOR, timeout=3000)
            company = (await company_el.text_content() or "") if company_el else ""

            location_el = await find_element_safely(card, INDEED_LOCATION_SELECTOR, timeout=3000)
            location = (await location_el.text_content() or "") if location_el else ""

            logger.debug(
                f"Extracting job card: title={title!r}, company={company!r}, url={job_url!r}"
            )

            # Check for easy apply badge on card first
            easy_apply_badge = await find_element_safely(
                card, INDEED_EASY_APPLY_BADGE, timeout=1000
            )
            if easy_apply_badge:
                apply_method = "easy_apply"
            else:
                # Click the card to open detail panel and check for apply button.
                # After a previous card is opened the DOM shifts and Playwright's
                # visibility checks fail. Use JS directly to bypass them.
                await card.evaluate("el => el.scrollIntoView({block: 'center'})")
                await title_el.evaluate("el => el.click()")
                await async_pause(0.5, 1)
                apply_button = await find_element_safely(
                    self.page, INDEED_APPLY_BUTTON, timeout=6000
                )
                apply_method = "easy_apply" if apply_button else "external"

            job = Job(
                job_title=sanitize_text(title),
                company_name=sanitize_text(company),
                location=sanitize_text(location),
                url=job_url,
                apply_method=apply_method,
            )
            return job

        except Exception as e:
            logger.warning(
                f"Failed to extract job from card: title={title!r}, company={company!r}, url={job_url!r} — {e}"
                if "title" in dir()
                else f"Failed to extract job from card (title not yet parsed): {e}"
            )
            await debug_capture(self.page, "extract_job_error")
            return None

    async def _extract_job_description_from_page(self, page: Any) -> str:
        """Extract job description text from an Indeed job detail page"""
        selectors = [
            "#jobDescriptionText",
            "[data-testid='jobsearch-jobDescriptionText']",
            ".jobsearch-jobDescriptionText",
            "#job-description",
        ]
        for selector in selectors:
            try:
                el = await find_element_safely(page, selector, timeout=3000)
                if el:
                    text = await el.text_content()
                    if text:
                        return text.strip()
            except Exception:
                continue
        logger.debug("Could not extract job description from Indeed page")
        return ""

    async def _extract_company_description(self, page: Any) -> str:
        """Extract company description from the 'About the company' section of an Indeed job page"""
        selectors = [
            "[data-testid='jobsearch-CompanyInfoContainer']",
            "#companyInfo",
            ".jobsearch-CompanyInfoWithoutHeaderImage",
            ".jobsearch-CompanyInfoContainer",
        ]
        for selector in selectors:
            try:
                el = await find_element_safely(page, selector, timeout=2000)
                if el:
                    text = await el.text_content()
                    if text:
                        text = text.strip()
                        if len(text) > 20:
                            logger.debug(f"Found company description using selector: {selector}")
                            return text
            except Exception:
                continue
        logger.debug("Could not extract company description from Indeed page")
        return ""

    async def _get_button_link(self, page: Any) -> str:
        """Click the external apply button and return the URL it opens in a new tab."""
        apply_selectors = [
            "a[data-testid='applyButton']",
            "a[aria-label*='Apply on']",
            ".ia-BasePage-applyButton",
            "a[data-jk][href*='apply']",
        ]
        for selector in apply_selectors:
            try:
                elements = await find_elements_safely(page, selector)
                for button in elements:
                    if not (await button.is_visible() and await button.is_enabled()):
                        continue
                    async with page.context.expect_page() as new_page_info:
                        await button.click(timeout=3000)
                    new_page = await new_page_info.value
                    await async_pause()
                    link = new_page.url
                    await new_page.close()
                    logger.debug(f"External apply link obtained: {link}")
                    return link
            except Exception as e:
                logger.debug(f"Failed to get external apply link with selector {selector!r}: {e}")
                continue
        logger.warning("Could not find external apply button on Indeed job page")
        return ""

    async def _dismiss_overlays(self) -> None:
        """Dismiss Indeed overlay portals that intercept clicks"""
        for selector in ["ifl-portal", "div.gnav-hovbc7"]:
            try:
                count = await self.page.locator(selector).count()
                if count > 0:
                    await self.page.evaluate(
                        f"document.querySelectorAll('{selector}').forEach(el => el.remove())"
                    )
                    logger.debug(f"Dismissed {count} overlay(s) matching '{selector}'")
            except Exception:
                pass

    async def _current_page_signature(self) -> str:
        """URL plus the first job card id, to tell one result page from the next"""
        try:
            first_card = await find_element_safely(
                self.page, INDEED_JOB_TITLE_SELECTOR, timeout=5000
            )
            first_jk = (await first_card.get_attribute("data-jk") or "") if first_card else ""
        except Exception as e:
            logger.debug(f"Could not read the first job card of the page: {e}")
            first_jk = ""
        return f"{self.page.url}|{first_jk}"

    async def _go_to_next_page(self) -> bool:
        """Click next page button. Returns True if navigated, False if last page reached."""
        try:
            next_btn = await find_element_safely(self.page, INDEED_NEXT_PAGE_SELECTOR, timeout=5000)
            if not next_btn:
                logger.info("No next page button found - reached last page")
                return False
            signature_before = await self._current_page_signature()
            await self._dismiss_overlays()
            clicked = await safe_click(self.page, INDEED_NEXT_PAGE_SELECTOR, timeout=5000)
            if not clicked:
                logger.debug("Normal click failed, retrying with force")
                await next_btn.click(force=True, timeout=5000)
            try:
                await self.page.wait_for_load_state("domcontentloaded")
            except Exception as e:
                # The click often advances the page without the load state ever
                # settling; the page content itself decides whether it worked
                logger.debug(f"Waiting for the next page to load timed out: {e}")
            await async_pause(1, 2)
            if await self._current_page_signature() == signature_before:
                logger.warning("Next page button was clicked but the results did not change")
                await debug_capture(self.page, "next_page_not_changed")
                return False
            self.page_num += 1
            logger.info(f"Moved to page {self.page_num + 1}")
            emit_event(
                "page_changed", f"Moving to page {self.page_num + 1}", page_num=self.page_num
            )
            return True
        except Exception as e:
            logger.warning(f"Could not navigate to next page: {e}")
            await debug_capture(self.page, "next_page_error")
            return False
