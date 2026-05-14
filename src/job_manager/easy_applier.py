import base64
import os
import traceback
from abc import ABC, abstractmethod
from typing import Any, List, Tuple

from httpx import HTTPStatusError

from config.logger_config import logger
from src.pydantic_models.job_models import Job, Question
from src.utils.browser_utils import debug_capture
from src.utils.utils import ConfigError, async_pause, load_yaml_file, sanitize_text, save_yaml_file


class NoInfoException(Exception):
    pass


class BaseEasyApplier(ABC):
    def __init__(self) -> None:
        super().__init__()
        self.ready_made_resume_path = None
        self.submitted_resume_path = None
        self.already_applied_at = None
        self.already_applied_at_text = None

    @abstractmethod
    async def apply_to_job(self, job: Job) -> None:
        pass

    @abstractmethod
    async def job_easy_apply(self, job: Job) -> Tuple[str, str]:
        pass

    @abstractmethod
    async def _handle_terms_of_service(self, section: Any) -> bool:
        pass

    @abstractmethod
    async def _find_and_handle_radio_question(self, section: Any) -> bool:
        pass

    @abstractmethod
    async def _find_and_handle_checkbox_question(self, section: Any) -> bool:
        pass

    @abstractmethod
    async def _find_and_handle_textbox_question(self, section: Any) -> bool:
        pass

    @abstractmethod
    async def _find_and_handle_dropdown_question(self, section: Any) -> bool:
        pass

    async def _find_and_handle_date_question(self, section: Any) -> bool:
        return False

    async def _create_and_upload_resume(self, element: Any, job: Job) -> None:
        file_path_pdf = await self._resolve_resume_upload_path(job)

        try:
            abs_path = os.path.abspath(file_path_pdf)
            await element.set_input_files(abs_path)
            self.submitted_resume_path = abs_path
            await async_pause(1, 2)
            logger.debug(f"Resume created and uploaded successfully: {file_path_pdf}")
        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Resume upload failed: {tb_str}")
            await debug_capture(self.page, "resume_upload_error")
            raise Exception(f"Upload failed: \nTraceback:\n{tb_str}")

    async def _resolve_resume_upload_path(self, job: Job) -> str:
        """Generate or resolve the resume file path to upload."""
        try:
            os.makedirs(self.generated_resume_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create directory: {self.generated_resume_dir}. Error: {e}")
            raise

        generator_ready = (
            getattr(self, "resume_generator_manager", None) is not None
            and getattr(self.resume_generator_manager, "selected_style", None) is not None
        )
        if generator_ready:
            file_path_pdf = os.path.join(
                self.generated_resume_dir, f"CV_{job.company_name}_{job.job_title}.pdf"
            )
            if os.path.exists(file_path_pdf):
                logger.info(f"Resume already exists, reusing cached file: {file_path_pdf}")
            else:
                while True:
                    try:
                        resume_pdf_base64 = await self.resume_generator_manager.pdf_base64()
                        with open(file_path_pdf, "wb") as f:
                            f.write(base64.b64decode(resume_pdf_base64))
                        logger.info(f"Resume successfully generated and saved to: {file_path_pdf}")
                        break
                    except HTTPStatusError as e:
                        if e.response.status_code == 429:
                            retry_after = e.response.headers.get("retry-after")
                            retry_after_ms = e.response.headers.get("retry-after-ms")
                            if retry_after:
                                wait_time = int(retry_after)
                            elif retry_after_ms:
                                wait_time = int(retry_after_ms) / 1000.0
                            else:
                                wait_time = 20
                            logger.warning(
                                f"Rate limit exceeded, waiting {wait_time}s before retrying..."
                            )
                            await async_pause(wait_time, wait_time + 1)
                        else:
                            logger.error(f"HTTP error: {e}")
                            raise
                    except Exception as e:
                        logger.error(f"Failed to generate resume: {e}")
                        if "RateLimitError" in str(e):
                            logger.warning("Rate limit error encountered, retrying...")
                            await async_pause(20, 40)
                        else:
                            raise
        elif self.ready_made_resume_path is not None:
            file_path_pdf = os.path.abspath(str(self.ready_made_resume_path))
            logger.info(f"Using ready-made resume: {file_path_pdf}")
        else:
            raise NoInfoException(
                "No resume generator style selected and no ready-made resume configured"
            )

        file_size = os.path.getsize(file_path_pdf)
        max_file_size = 2 * 1024 * 1024  # 2 MB
        if file_size > max_file_size:
            logger.error(f"Resume file size exceeds 2 MB: {file_size} bytes")
            raise ValueError("Resume file size exceeds the maximum limit of 2 MB.")

        file_extension = os.path.splitext(file_path_pdf)[1].lower()
        if file_extension not in {".pdf", ".doc", ".docx"}:
            logger.error(f"Invalid resume file format: {file_extension}")
            raise ValueError(
                "Resume file format is not allowed. Only PDF, DOC, and DOCX formats are supported."
            )

        return os.path.abspath(file_path_pdf)

    async def _process_form_section(self, section: Any) -> None:
        """Process form section by dispatching to appropriate handler (async)"""
        logger.debug("Processing form section")
        if await self._handle_terms_of_service(section):
            logger.debug("Handled terms of service")
            return
        if await self._find_and_handle_radio_question(section):
            logger.debug("Handled radio question")
            return
        if await self._find_and_handle_checkbox_question(section):
            logger.debug("Handled checkbox question")
            return
        if await self._find_and_handle_dropdown_question(section):
            logger.debug("Handled dropdown question")
            return
        if await self._find_and_handle_date_question(section):
            logger.debug("Handled date question")
            return
        if await self._find_and_handle_textbox_question(section):
            logger.debug("Handled textbox question")
            return
        logger.debug("Form section not handled")

    def _save_questions(self, question_data: Question) -> None:
        """Save questions to YAML file"""
        question_data.question = sanitize_text(question_data.question)

        logger.debug(f"Checking if question data already exists: {question_data}")
        try:
            should_be_saved: bool = not self._answer_contains_company_name(question_data.answer)
            self.all_questions = [
                q for q in self.all_questions if q.question != question_data.question
            ]
            if should_be_saved:
                logger.debug("New question found, appending to YAML")
                self.all_questions.append(question_data)
                save_yaml_file(
                    self.answers_file, [question.model_dump() for question in self.all_questions]
                )
            else:
                logger.debug("Question already exists, skipping save")
        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Error saving questions data to YAML file: {tb_str}")
            raise Exception(f"Error saving questions data to YAML file: \nTraceback:\n{tb_str}")

    def _answer_contains_company_name(self, answer: str) -> bool:
        """Check if answer contains company name"""
        return (
            isinstance(answer, str)
            and self.current_job.company_name is not None
            and self.current_job.company_name in answer
        )

    def _is_no_info_answer(self, answer: Any) -> bool:
        return isinstance(answer, str) and answer.strip().lower().startswith("no info")

    def _find_cached_question(
        self, question_text: str, question_type: str | None = None
    ) -> Question | None:
        """Find a cached answer by exact question text, preferring the same field type."""
        current_question_sanitized = sanitize_text(question_text)
        same_type_match = None
        any_type_match = None

        for item in self.all_questions:
            if item.question != current_question_sanitized:
                continue

            if item.question_type == question_type:
                same_type_match = item
                break

            if any_type_match is None:
                any_type_match = item

        return same_type_match or any_type_match

    def _load_questions(self) -> List[Question]:
        logger.info(f"Loading questions from YAML file: {self.answers_file}")
        try:
            answers_file = self.answers_file
            if not answers_file.exists():
                legacy_answers_file = answers_file.parent.parent / answers_file.name
                if legacy_answers_file.exists():
                    logger.info(
                        "Using legacy shared answers file because platform-specific file is missing: "
                        f"{legacy_answers_file}"
                    )
                    self.answers_file = legacy_answers_file
                    answers_file = legacy_answers_file

            data = load_yaml_file(answers_file)
            logger.info("Questions loaded successfully from YAML")
            if not data:
                return []
            return [Question(**question) for question in data]
        except ConfigError:
            logger.warning("Answers file not found, returning empty list")
            return []
        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Error loading questions data from YAML file: {tb_str}")
            raise Exception(f"Error loading questions data from YAML file: \nTraceback:\n{tb_str}")
