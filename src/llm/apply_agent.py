import asyncio
import os
from datetime import datetime
from pathlib import Path

from browser_use import Agent, Browser, ChatAnthropic, ChatGoogle, ChatOllama, ChatOpenAI, Tools
from browser_use.tools.views import UploadFileAction

from config.app_config import APPLY_AGENT_MODEL, HEADLESS_MODE, LLM_MODEL_TYPE
from config.constants import CUSTOM_COST_PER_TOKEN, LOG_DIR, RESUME_DIR, cost_per_token
from config.logger_config import logger
from src.dashboard.runtime import emit_event
from src.pydantic_models.log_models import LLMCall
from src.utils.utils import append_yaml_file, get_ready_made_resume


class ApplyAgent:
    def __init__(
        self,
        api_key: str = None,
        browser_storage_state: str = None,
        llm_api_url: str = None,
        user_email: str = None,
    ) -> None:
        self.api_key = api_key
        self.user_email = user_email
        self.model = APPLY_AGENT_MODEL
        self.model_type = LLM_MODEL_TYPE
        self.llm_api_url = llm_api_url
        self.llm = self.select_model_type(self.model_type, self.llm_api_url)
        self.calls_log = os.path.join(Path(LOG_DIR), "llm_api_calls.yaml")
        self.agent = None
        self.resume_readable = None
        self.browser_storage_state = str(Path(browser_storage_state).absolute())
        storage_state = (
            self.browser_storage_state if Path(self.browser_storage_state).exists() else None
        )
        if storage_state is None:
            logger.warning(
                f"Browser storage state file not found at {self.browser_storage_state}. "
                "Continuing without persisted cookies/localStorage."
            )
        self.storage_state = storage_state

    def _create_browser(self) -> Browser:
        return Browser(headless=HEADLESS_MODE, storage_state=self.storage_state)

    def select_model_type(self, model_type: str, llm_api_url: str) -> None:
        """Select the model to use."""
        self.model_type = model_type
        if model_type == "gemini":
            if not self.api_key:
                raise ValueError("API key is required for Gemini model")
            llm = ChatGoogle(api_key=self.api_key, model=self.model)
        elif model_type == "openai":
            if not self.api_key:
                raise ValueError("API key is required for OpenAI model")
            llm = ChatOpenAI(api_key=self.api_key, model=self.model, reasoning_effort="minimal")
        elif model_type == "claude":
            if not self.api_key:
                raise ValueError("API key is required for Claude model")
            llm = ChatAnthropic(api_key=self.api_key, model=self.model)
        elif model_type == "ollama":
            if llm_api_url:
                llm = ChatOllama(model=self.model, host=llm_api_url)
            else:
                llm = ChatOllama(model=self.model)
        elif model_type == "openrouter":
            llm = ChatOpenAI(
                api_key=self.api_key,
                model=self.model,
                base_url="https://openrouter.ai/api/v1",
            )
        elif model_type == "nvidia_nim":
            if not self.api_key:
                raise ValueError("API key is required for NVIDIA NIM model")
            llm = ChatOpenAI(
                api_key=self.api_key,
                model=self.model,
                base_url="https://integrate.api.nvidia.com/v1",
            )
        elif model_type == "groq":
            if not self.api_key:
                raise ValueError("API key is required for Groq model")
            llm = ChatOpenAI(
                api_key=self.api_key,
                model=self.model,
                base_url="https://api.groq.com/openai/v1",
            )
        elif model_type == "cerebras":
            if not self.api_key:
                raise ValueError("API key is required for Cerebras model")
            llm = ChatOpenAI(
                api_key=self.api_key,
                model=self.model,
                base_url="https://api.cerebras.ai/v1",
            )
        elif model_type == "openai_compatible":
            if not llm_api_url:
                raise ValueError("llm_api_url is required for openai_compatible model type")
            llm = ChatOpenAI(
                api_key=self.api_key,
                model=self.model,
                base_url=llm_api_url,
            )
        else:
            raise ValueError(f"Unsupported model type: {model_type}")
        return llm

    def set_resume(self, resume_readable: str) -> None:
        """Add resume for analysis."""
        self.resume_readable = resume_readable

    async def apply(self, job_url: str) -> None:
        """Apply to the job using AI Agent"""
        resume_pdf_path = str(get_ready_made_resume())
        emit_event("agent_apply_started", "External apply agent started", url=job_url)

        tools = Tools()

        @tools.action(
            description="Get an UploadFileAction for my resume PDF file (use with upload_file_to_element if needed)"
        )
        async def upload_resume(browser_session, index: int = 0):  # noqa: ARG001
            return UploadFileAction(path=resume_pdf_path, index=index)

        browser_storage_state = self.browser_storage_state

        @tools.action(
            description=(
                "Call this when the website requires email verification or confirmation "
                "before you can proceed. This pauses the task and asks the user to verify "
                "their email, then saves the browser session so the user won't need to "
                "log in again."
            )
        )
        async def wait_for_email_verification(browser_session):
            print("\n" + "=" * 60)
            print("EMAIL VERIFICATION REQUIRED")
            print("Please check your email and confirm your account.")
            print("Once done, press Enter to continue...")
            print("=" * 60 + "\n")
            await asyncio.get_event_loop().run_in_executor(None, input)
            await browser_session.export_storage_state(output_path=browser_storage_state)
            logger.info(f"Browser session saved to {browser_storage_state}")
            return "User confirmed email verification. Browser session saved. Proceeding with the application."

        task = f"""
        - Your goal is to apply to the job at: {job_url}
        - Use the information from my resume (source of truth) and any additional information already present on the page.
        - If you cannot apply, finish the task (do not try different URLs).

        - Follow these instructions carefully:
            - If anything pops up that blocks the form, close it and continue.
            - Do not skip required fields. If an optional field is present, fill it if possible using my resume/context.
            - Fill the form from top to bottom; do not skip a field to come back later.
            - Some text boxes may have dropdown suggestions: after filling a textbox, check for a dropdown and select the correct option.

        - Resume:
            - You may upload my resume PDF when the application asks for it.
            - The resume file is available as: {resume_pdf_path}
            - Prefer using the built-in upload_file_to_element action; if the page flow needs it, you can use the upload_resume tool to produce an UploadFileAction.

        - If you are asked to register an account, use my email: {self.user_email} and password: {self.user_email.split("@")[0] + "123456" if self.user_email else "unknown"}

        - If an email verification or confirmation step appears, call the wait_for_email_verification tool immediately — do NOT give up or mark the task as failed. After the tool returns, continue the application.

        - Before you start, create a step-by-step plan to complete the entire application. Delegate a step for each field/section you encounter.

        *** IMPORTANT ***
            - You are not done until you have either submitted the application OR confirmed you cannot apply.
            - At the end, structure your final_result as:
                1) a human-readable summary of all detections and actions performed
                2) a list of all questions encountered on the page (including any screening questions)
                3) a short final human-readable summary at the very end

        ## My resume text (source of truth):
        {self.resume_readable}
        """

        available_file_paths = [resume_pdf_path]

        browser = self._create_browser()
        try:
            self.agent = Agent(
                task=task,
                browser=browser,
                llm=self.llm,
                tools=tools,
                use_vision=False,
                use_thinking=False,
                # Cap browser-use churn: defaults (max_failures=5, step_timeout=180s) let
                # element-index drift loops eat tokens without ever raising.
                max_failures=3,
                step_timeout=60,
                save_conversation_path=Path(LOG_DIR).absolute() / "apply_agent_conversation",
                available_file_paths=available_file_paths,
            )
            await self.agent.run()
        finally:
            await browser.stop()

        self._log_token_usage(task)
        emit_event("agent_apply_completed", "External apply agent completed", url=job_url)

    def _log_token_usage(self, task: str) -> None:
        """Log AI Agent token usage and calculate the total cost"""
        token_usage = self.agent.token_cost_service.get_usage_tokens_for_model(self.model)
        input_tokens, output_tokens = token_usage.prompt_tokens, token_usage.completion_tokens
        total_tokens = input_tokens + output_tokens
        logger.info(
            f"Token usage - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}"
        )
        prompt_cost, completion_cost = cost_per_token(
            model=self.model.replace("google/", ""),
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            custom_cost_per_token=CUSTOM_COST_PER_TOKEN,
        )
        total_cost = prompt_cost + completion_cost
        logger.info(f"Total cost calculated: {total_cost}")

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            log_entry = LLMCall(
                model_name=self.model,
                timestamp=current_time,
                prompts={
                    "prompt_1": task,
                    "prompt_2": "<Some browser content>",
                },
                parsed_reply="<Some reply from agent>",
                total_tokens=total_tokens,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                response_time_seconds=0.0,
                total_cost=total_cost,
            )
            logger.debug(f"Log entry created: {log_entry}")
        except KeyError as e:
            logger.error(f"Error creating log entry: missing key {str(e)} in parsed_reply")
            raise

        append_yaml_file(Path(self.calls_log), log_entry.model_dump())

        return total_cost

    async def apply_to_job(self, job_url: str) -> tuple[str, str]:
        """Apply to job, handling event loop properly"""
        # Directly await the apply method since we're already in an async context
        try:
            await self.apply(job_url)
            return ("Success", "")
        except Exception as e:
            logger.error(f"Error applying to job: {e}")
            emit_event(
                "agent_apply_failed", "External apply agent failed", url=job_url, error=str(e)
            )
            return ("Error", str(e))


if __name__ == "__main__":
    """Test ApplyAgent functionality"""
    import traceback

    import dotenv

    from config.constants import BROWSER_STORAGE_STATE
    from src.pydantic_models.prompt_models import ResumeStructure
    from src.utils.utils import load_yaml_file

    async def test_apply_agent():
        """Test ApplyAgent with a real LinkedIn job posting"""
        logger.info("Starting ApplyAgent test...")

        try:
            # Load secrets for LLM
            secrets = dotenv.dotenv_values(".env")
            llm_api_key = secrets.get("llm_api_key", "")

            if not llm_api_key:
                logger.error("❌ LLM API key not found in .env file")
                return False

            # Initialize ApplyAgent
            apply_agent = ApplyAgent(
                llm_api_key, BROWSER_STORAGE_STATE, user_email=secrets.get("linkedin_email", "")
            )
            logger.info("ApplyAgent initialized successfully")

            # Load resume data
            RESUME_STRUCTURED_FILE = Path(RESUME_DIR) / "structured_resume.yaml"
            RESUME_TEXT_FILE = Path(RESUME_DIR) / "resume_text.txt"

            if not RESUME_STRUCTURED_FILE.exists():
                logger.error(f"❌ Resume structured file not found: {RESUME_STRUCTURED_FILE}")
                return False

            if not RESUME_TEXT_FILE.exists():
                logger.error(f"❌ Resume text file not found: {RESUME_TEXT_FILE}")
                return False

            # Load and set resume data
            resume_structured = load_yaml_file(RESUME_STRUCTURED_FILE)
            resume_structured = ResumeStructure(**resume_structured).model_dump()

            with open(RESUME_TEXT_FILE, "r") as f:
                resume_text = f.read()

            # Set resume and job for the agent
            apply_agent.set_resume(resume_text)
            logger.info("Resume and job data set successfully")

            # Test the apply_to_job method
            vacancy_url = "https://app.searchwithjack.com/jobs/4372944?utm_source=linkedin-direct-apply-4372944&comet_source=linkedin"
            logger.info(f"Testing ApplyAgent.apply_to_job method with job: {vacancy_url}")
            logger.info("This will open a browser and attempt to apply to the job...")

            # Run the application
            await apply_agent.apply_to_job(vacancy_url)

            logger.info("✅ ApplyAgent test completed successfully!")
            logger.info("Check the browser window to see the application process")
            return True

        except Exception as e:
            logger.error(f"❌ ApplyAgent test failed with error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    # Run the test
    success = asyncio.run(test_apply_agent())
    if success:
        print("✅ Test passed!")
    else:
        print("❌ Test failed!")
