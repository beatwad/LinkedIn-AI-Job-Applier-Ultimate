import os
import re
import textwrap
import threading
import time
import traceback
from abc import ABC, abstractmethod
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.messages.ai import AIMessage
from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langchain_core.prompt_values import StringPromptValue
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

import src.llm.prompts as prompts
from config.app_config import (
    EASY_APPLY_MODEL,
    FREE_TIER,
    FREE_TIER_RPM_LIMIT,
    JOB_IS_INTERESTING_THRESH,
    LLM_MODEL_TYPE,
    TEMPERATURE,
)
from config.constants import LOG_DIR, RESUME_DIR, cost_per_token
from config.logger_config import logger
from src.dashboard.runtime import emit_event
from src.pydantic_models.log_models import LLMCall
from src.pydantic_models.prompt_models import LinkedInMessageClassification, ResumeStructure
from src.utils.json_to_readable import transform_search_config_data, transform_vacancy_data
from src.utils.utils import append_yaml_file, pause

load_dotenv()


class AIModel(ABC):
    @abstractmethod
    def invoke(self, prompt: str) -> str:
        pass


class GeminiModel(AIModel):
    """Get access to Gemini model"""

    def __init__(self, api_key: str, llm_model: str, llm_proxy: str = None) -> None:
        from google.genai import types
        from langchain_google_genai import ChatGoogleGenerativeAI, HarmBlockThreshold, HarmCategory

        # os.environ["https_proxy"] = llm_proxy
        http_options = types.HttpOptions(
            client_args={"proxy": llm_proxy}, async_client_args={"proxy": llm_proxy}
        )
        self.google_api_key = api_key
        self.model = ChatGoogleGenerativeAI(
            model=llm_model,
            google_api_key=self.google_api_key,
            temperature=TEMPERATURE,
            thinking_level="minimal",
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            },
            http_options=http_options,
        )

    def invoke(self, prompt: ChatPromptTemplate) -> BaseMessage:
        logger.info("Got access to model via Gemini API")
        prompt_messages = [SystemMessage(content=prompts.custom_instructions)] + prompt.messages
        # randomly select one proxy after another until LLM request succeeds
        response = self.model.invoke(prompt_messages)
        return response


class OpenAIModel(AIModel):
    """Get access to OpenAI model"""

    def __init__(self, api_key: str, llm_model: str, llm_proxy: str = None) -> None:
        from langchain_openai import ChatOpenAI

        if llm_proxy:
            http_client = httpx.Client(proxy=llm_proxy)
        else:
            http_client = None
        self.llm_proxy = llm_proxy
        self.model_name = llm_model
        self.openai_api_key = api_key
        is_reasoning_model = (
            "o1" in self.model_name
            or "o3" in self.model_name
            or "o4" in self.model_name
            or "gpt-5" in self.model_name
        )
        extra = {"reasoning_effort": "minimal"} if is_reasoning_model else {}
        self.model = ChatOpenAI(
            model_name=self.model_name,
            openai_api_key=self.openai_api_key,
            http_client=http_client,
            temperature=1 if is_reasoning_model or "gpt-5" in self.model_name else TEMPERATURE,
            presence_penalty=0,
            frequency_penalty=0,
            timeout=60,
            **extra,
        )

    def invoke(self, prompt: ChatPromptTemplate) -> BaseMessage:
        logger.info("Got access to model via OpenAI API")
        prompt_messages = [SystemMessage(content=prompts.custom_instructions)] + prompt.messages
        response = self.model.invoke(prompt_messages)
        return response


class ClaudeModel(AIModel):
    """Get access to Claude model"""

    def __init__(self, api_key: str, llm_model: str) -> None:
        from langchain_anthropic import ChatAnthropic

        self.model = ChatAnthropic(model=llm_model, api_key=api_key, temperature=TEMPERATURE)

    def invoke(self, prompt: str) -> BaseMessage:
        response = self.model.invoke(prompt)
        logger.debug("Successfully got access to model via Claude API")
        return response


class OllamaModel(AIModel):
    """Get access to Ollama model"""

    def __init__(self, llm_model: str, llm_api_url: str) -> None:
        from langchain_ollama import ChatOllama

        if llm_api_url:
            logger.debug(f"Using Ollama with API URL: {llm_api_url}")
            self.model = ChatOllama(model=llm_model, base_url=llm_api_url)
        else:
            self.model = ChatOllama(model=llm_model)

    def invoke(self, prompt: str) -> BaseMessage:
        response = self.model.invoke(prompt)
        logger.debug("Successfully got access to model via Ollama API")
        return response


class OpenRouterModel(AIModel):
    """Get access to models via OpenRouter API"""

    def __init__(self, api_key: str, llm_model: str, llm_proxy: str = None) -> None:
        from langchain_openai import ChatOpenAI

        http_client = httpx.Client(proxy=llm_proxy) if llm_proxy else None
        self.llm_proxy = llm_proxy
        self.model_name = llm_model
        self.model = ChatOpenAI(
            model_name=self.model_name,
            openai_api_key=api_key,
            openai_api_base="https://openrouter.ai/api/v1",
            http_client=http_client,
            temperature=TEMPERATURE,
            timeout=60,
        )

    def invoke(self, prompt: ChatPromptTemplate) -> BaseMessage:
        logger.info("Got access to model via OpenRouter API")
        prompt_messages = [SystemMessage(content=prompts.custom_instructions)] + prompt.messages
        response = self.model.invoke(prompt_messages)
        return response


class NvidiaNimModel(AIModel):
    """Get access to models via NVIDIA NIM API (OpenAI-compatible endpoint)"""

    def __init__(self, api_key: str, llm_model: str, llm_proxy: str = None) -> None:
        from langchain_openai import ChatOpenAI

        http_client = httpx.Client(proxy=llm_proxy) if llm_proxy else None
        self.llm_proxy = llm_proxy
        self.model_name = llm_model
        self.model = ChatOpenAI(
            model_name=self.model_name,
            openai_api_key=api_key,
            openai_api_base="https://integrate.api.nvidia.com/v1",
            http_client=http_client,
            temperature=TEMPERATURE,
            timeout=120,
        )

    def invoke(self, prompt: ChatPromptTemplate) -> BaseMessage:
        logger.info("Got access to model via NVIDIA NIM API")
        prompt_messages = [SystemMessage(content=prompts.custom_instructions)] + prompt.messages
        response = self.model.invoke(prompt_messages)
        return response


class GroqModel(AIModel):
    """Get access to models via Groq API (OpenAI-compatible endpoint)"""

    def __init__(self, api_key: str, llm_model: str, llm_proxy: str = None) -> None:
        from langchain_openai import ChatOpenAI

        http_client = httpx.Client(proxy=llm_proxy) if llm_proxy else None
        self.llm_proxy = llm_proxy
        self.model_name = llm_model
        self.model = ChatOpenAI(
            model_name=self.model_name,
            openai_api_key=api_key,
            openai_api_base="https://api.groq.com/openai/v1",
            http_client=http_client,
            temperature=TEMPERATURE,
            timeout=60,
        )

    def invoke(self, prompt: ChatPromptTemplate) -> BaseMessage:
        logger.info("Got access to model via Groq API")
        prompt_messages = [SystemMessage(content=prompts.custom_instructions)] + prompt.messages
        response = self.model.invoke(prompt_messages)
        return response


class CerebrasModel(AIModel):
    """Get access to models via Cerebras API (OpenAI-compatible endpoint)"""

    def __init__(self, api_key: str, llm_model: str, llm_proxy: str = None) -> None:
        from langchain_openai import ChatOpenAI

        http_client = httpx.Client(proxy=llm_proxy) if llm_proxy else None
        self.llm_proxy = llm_proxy
        self.model_name = llm_model
        self.model = ChatOpenAI(
            model_name=self.model_name,
            openai_api_key=api_key,
            openai_api_base="https://api.cerebras.ai/v1",
            http_client=http_client,
            temperature=TEMPERATURE,
            timeout=60,
        )

    def invoke(self, prompt: ChatPromptTemplate) -> BaseMessage:
        logger.info("Got access to model via Cerebras API")
        prompt_messages = [SystemMessage(content=prompts.custom_instructions)] + prompt.messages
        response = self.model.invoke(prompt_messages)
        return response


class OpenAICompatibleModel(AIModel):
    """Get access to models via any OpenAI-compatible endpoint"""

    def __init__(
        self, api_key: str, llm_model: str, llm_api_url: str, llm_proxy: str = None
    ) -> None:
        from langchain_openai import ChatOpenAI

        if not llm_api_url:
            raise ValueError("llm_api_url is required for openai_compatible model type")

        http_client = httpx.Client(proxy=llm_proxy) if llm_proxy else None
        self.model_name = llm_model
        is_reasoning_model = (
            "o1" in self.model_name
            or "o3" in self.model_name
            or "o4" in self.model_name
            or "gpt-5" in self.model_name
        )
        extra = {"reasoning_effort": "minimal"} if is_reasoning_model else {}
        self.model = ChatOpenAI(
            model_name=self.model_name,
            openai_api_key=api_key,
            openai_api_base=llm_api_url,
            http_client=http_client,
            temperature=1 if is_reasoning_model else TEMPERATURE,
            timeout=60,
            **extra,
        )

    def invoke(self, prompt: ChatPromptTemplate) -> BaseMessage:
        logger.info("Got access to model via OpenAI-compatible endpoint")
        prompt_messages = [SystemMessage(content=prompts.custom_instructions)] + prompt.messages
        response = self.model.invoke(prompt_messages)
        return response


# class xAIModel(AIModel):
#     """Get access to xAI model"""

#     def __init__(self, api_key: str, llm_model: str) -> None:
#         from langchain_xai import ChatXAI

#         self.model = ChatXAI(model=llm_model, xai_api_key=api_key)

#     def invoke(self, prompt: str) -> BaseMessage:
#         response = self.model.invoke(prompt)
#         logger.debug("Successfully got access to model via Ollama API")
#         return response


# class HuggingFaceModel(AIModel):
#     """Get access to Hugging Face model"""

#     def __init__(self, api_key: str, llm_model: str) -> None:
#         from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

#         self.model = HuggingFaceEndpoint(
#             repo_id=llm_model, huggingfacehub_api_token=api_key, temperature=TEMPERATURE
#         )
#         self.chatmodel = ChatHuggingFace(llm=self.model)

#     def invoke(self, prompt: str) -> BaseMessage:
#         response = self.chatmodel.invoke(prompt)
#         logger.debug("Successfully got access to model via Hugging Face API")
#         return response


class AIAdapter:
    """Class for accessing LLM models from different companies via API"""

    def __init__(self, api_key: str = None, llm_proxy: str = None, llm_api_url: str = None):
        self.model_type = LLM_MODEL_TYPE
        self.easy_apply_model = EASY_APPLY_MODEL
        self.free_tier = FREE_TIER
        self.free_tier_rpm_limit = FREE_TIER_RPM_LIMIT
        self.free_tier_request_queue = deque(maxlen=self.free_tier_rpm_limit)
        self.model = self._create_model(api_key, llm_proxy, llm_api_url)

    def _create_model(self, api_key: str, llm_proxy: str, llm_api_url: str) -> AIModel:
        logger.info(f"Using {self.model_type} from {self.easy_apply_model}")

        if self.model_type == "gemini":
            if not api_key:
                raise ValueError("API key is required for Gemini model")
            return GeminiModel(api_key, self.easy_apply_model, llm_proxy)
        elif self.model_type == "openai":
            if not api_key:
                raise ValueError("API key is required for OpenAI model")
            return OpenAIModel(api_key, self.easy_apply_model, llm_proxy)
        elif self.model_type == "claude":
            if not api_key:
                raise ValueError("API key is required for Claude model")
            return ClaudeModel(api_key, self.easy_apply_model)
        elif self.model_type == "ollama":
            return OllamaModel(self.easy_apply_model, llm_api_url)
        elif self.model_type == "openrouter":
            return OpenRouterModel(api_key, self.easy_apply_model, llm_proxy)
        elif self.model_type == "nvidia_nim":
            if not api_key:
                raise ValueError("API key is required for NVIDIA NIM model")
            return NvidiaNimModel(api_key, self.easy_apply_model, llm_proxy)
        elif self.model_type == "groq":
            if not api_key:
                raise ValueError("API key is required for Groq model")
            return GroqModel(api_key, self.easy_apply_model, llm_proxy)
        elif self.model_type == "cerebras":
            if not api_key:
                raise ValueError("API key is required for Cerebras model")
            return CerebrasModel(api_key, self.easy_apply_model, llm_proxy)
        elif self.model_type == "openai_compatible":
            return OpenAICompatibleModel(api_key, self.easy_apply_model, llm_api_url, llm_proxy)
        # elif self.model_type == "xai":
        #     return xAIModel(api_key, self.easy_apply_model)
        # elif self.model_type == "huggingface":
        #     return HuggingFaceModel(api_key, self.easy_apply_model)
        else:
            raise ValueError(f"Unsupported model type: {LLM_MODEL_TYPE}")

    def invoke(self, prompt: str) -> str:
        if self.free_tier:
            # if free tier mode is activated and current model RPM is greater than the limit,
            # wait for the specified time before invoking the model to avoid rate limit errors
            if len(self.free_tier_request_queue) >= self.free_tier_rpm_limit:
                first_request_timestamp = self.free_tier_request_queue.popleft()
                time_delta = datetime.now() - first_request_timestamp
                if time_delta < timedelta(seconds=60):
                    pause(60 - time_delta.total_seconds(), 60 - time_delta.total_seconds() + 1)
            self.free_tier_request_queue.append(datetime.now())
        return self.model.invoke(prompt)


class LLMLogger:
    """Class for logging all events that occur when working with LLM"""

    def __init__(self):
        self.calls_log = os.path.join(Path(LOG_DIR), "llm_api_calls.yaml")
        logger.info("LLMLogger successfully initialized")

    def log_request(
        self,
        prompts,
        parsed_reply: Dict[str, Dict],
        response_time_seconds: float = 0.0,
        context: Dict[str, str] | None = None,
    ) -> None:
        """Method for logging all LLM operations"""
        logger.debug("Starting execution of log_request method")
        logger.debug("Prompts received")
        logger.debug("Parsed response received")

        try:
            logger.debug(f"Log file path determined: {self.calls_log}")
        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Error determining log file path: {tb_str}")
            raise

        if isinstance(prompts, StringPromptValue):
            logger.debug("Prompts have StringPromptValue type")
            prompts = {"prompt_1": prompts.text}
        elif isinstance(prompts, Dict):
            logger.debug("Prompts have Dict type")
            try:
                prompts = {
                    f"prompt_{i + 1}": prompt.content for i, prompt in enumerate(prompts.messages)
                }
                logger.debug("Prompts converted to dictionary")
            except Exception:
                tb_str = traceback.format_exc()
                logger.error(f"Error converting prompts to dictionary: {tb_str}")
                raise
        else:
            logger.debug("Unknown prompt type, attempting default conversion")
            try:
                prompts = {
                    f"prompt_{i + 1}": prompt.content for i, prompt in enumerate(prompts.messages)
                }
                logger.debug("Prompts converted to dictionary using default method")
            except Exception:
                tb_str = traceback.format_exc()
                logger.error(f"Error converting prompts using default method: {tb_str}")
                raise

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            token_usage = parsed_reply["usage_metadata"]
            output_tokens = token_usage["output_tokens"]
            input_tokens = token_usage["input_tokens"]
            total_tokens = token_usage["total_tokens"]
            logger.info(
                f"Token usage - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}"
            )
        except KeyError as e:
            logger.error(f"Key error in parsed_reply structure: {str(e)}")
            raise

        try:
            model_name = parsed_reply["response_metadata"]["model_name"]
            logger.debug(f"Model name: {model_name}")
        except KeyError as e:
            logger.error(f"Key error in response_metadata: {str(e)}")
            raise

        prompt_cost, completion_cost = cost_per_token(
            model=EASY_APPLY_MODEL.replace("google/", ""),
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
        )
        total_cost = prompt_cost + completion_cost
        logger.info(f"Total cost calculated: {total_cost}")

        try:
            log_entry = LLMCall(
                model_name=model_name,
                timestamp=current_time,
                prompts=prompts,
                parsed_reply=parsed_reply["content"],
                total_tokens=total_tokens,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                response_time_seconds=round(response_time_seconds, 3),
                total_cost=total_cost,
                job_url=(context or {}).get("job_url", ""),
                job_title=(context or {}).get("job_title", ""),
                company_name=(context or {}).get("company_name", ""),
            )
            logger.debug(f"Log entry created: {log_entry}")
        except KeyError as e:
            logger.error(f"Error creating log entry: missing key {str(e)} in parsed_reply")
            raise

        # Append the log entry to the call log file
        append_yaml_file(Path(self.calls_log), log_entry.model_dump())
        logger.info(f"LLM call log entry appended to {self.calls_log}")


class LoggerChatModel:
    """
    Class for interacting with language model (LLM) and logging all operations.
    This class processes requests to the language model, parses and logs responses, and handles
    possible errors such as rate limit exceeded or network errors.
    """

    def __init__(self, llm: GeminiModel, context_provider=None, call_listener=None):
        self.llm = llm
        self.llm_logger = LLMLogger()
        self.context_provider = context_provider
        self.call_listener = call_listener
        logger.info(f"LoggerChatModel successfully initialized, LLM: {llm}")

    def __call__(self, messages: List[Dict[str, str]]) -> str:
        """
        Execute LLM call, process response and log the entire process.
        """
        # logger.debug(f"Entering __call__ method with messages: {messages}")
        while True:
            try:
                logger.info("Attempting LLM call")

                started_at = time.perf_counter()
                reply = self.llm.invoke(messages)
                response_time_seconds = time.perf_counter() - started_at
                logger.debug(f"Response from LLM: {reply}")

                parsed_reply = self.parse_llmresult(reply)
                logger.info(f"Successfully parsed LLM result: {parsed_reply}")

                context = self.context_provider() if self.context_provider else {}
                self.llm_logger.log_request(
                    prompts=messages,
                    parsed_reply=parsed_reply,
                    response_time_seconds=response_time_seconds,
                    context=context,
                )

                if self.call_listener:
                    self.call_listener(
                        response_time_seconds=response_time_seconds,
                        parsed_reply=parsed_reply,
                        context=context,
                    )

                return reply

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTPStatusError occurred: {str(e)}")
                if e.response.status_code == 429:
                    retry_after = e.response.headers.get("retry-after")
                    retry_after_ms = e.response.headers.get("retry-after-ms")

                    if retry_after:
                        wait_time = int(retry_after)
                        logger.warning(
                            f"Rate limit exceeded. Waiting {wait_time} seconds before retry (from 'retry-after' header)..."
                        )
                        pause(wait_time, wait_time + 1)
                    elif retry_after_ms:
                        wait_time = int(retry_after_ms) / 1000.0
                        logger.warning(
                            f"Rate limit exceeded. Waiting {wait_time} seconds before retry (from 'retry-after-ms' header)..."
                        )
                        pause(wait_time, wait_time + 1)
                    else:
                        wait_time = 30
                        logger.warning(
                            f"'retry-after' header not found. Waiting {wait_time} seconds before retry (default)..."
                        )
                        pause(wait_time, wait_time + 1)
                else:
                    logger.error(
                        f"HTTP error occurred with status: {e.response.status_code}, waiting 30 seconds before retry"
                    )
                    pause(30, 31)

    def parse_llmresult(self, llmresult: AIMessage) -> Dict[str, Dict]:
        """Parse LLM result"""
        logger.info("Parsing LLM result")

        try:
            if hasattr(llmresult, "usage_metadata") and llmresult.usage_metadata is not None:
                content = llmresult.content
                response_metadata = llmresult.response_metadata
                id_ = llmresult.id
                usage_metadata = llmresult.usage_metadata

                parsed_result = {
                    "content": content,
                    "response_metadata": {
                        "model_name": response_metadata.get("model_name", ""),
                        "system_fingerprint": response_metadata.get("system_fingerprint", ""),
                        "finish_reason": response_metadata.get("finish_reason", ""),
                        "logprobs": response_metadata.get("logprobs", None),
                    },
                    "id": id_,
                    "usage_metadata": {
                        "input_tokens": usage_metadata.get("input_tokens", 0),
                        "output_tokens": usage_metadata.get("output_tokens", 0),
                        "total_tokens": usage_metadata.get("total_tokens", 0),
                    },
                }
            else:
                try:
                    content = llmresult.content
                    response_metadata = llmresult.response_metadata
                    id_ = llmresult.id

                    # Handle the case where token_usage might not be in response_metadata
                    if "token_usage" in response_metadata:
                        token_usage = response_metadata["token_usage"]
                        input_tokens = token_usage.prompt_tokens
                        output_tokens = token_usage.completion_tokens
                        total_tokens = token_usage.total_tokens
                    else:
                        # Default values when token_usage is not available
                        input_tokens = 0
                        output_tokens = 0
                        total_tokens = 0

                    parsed_result = {
                        "content": content,
                        "response_metadata": {
                            "model_name": response_metadata.get("model", ""),
                            "finish_reason": response_metadata.get("finish_reason", ""),
                        },
                        "id": id_,
                        "usage_metadata": {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "total_tokens": total_tokens,
                        },
                    }
                except Exception:
                    tb_str = traceback.format_exc()
                    logger.error(f"Error processing result without usage_metadata: {tb_str}")
                    # Create a minimal parsed result with defaults
                    parsed_result = {
                        "content": llmresult.content if hasattr(llmresult, "content") else "",
                        "response_metadata": {"model_name": "unknown", "finish_reason": "unknown"},
                        "id": llmresult.id if hasattr(llmresult, "id") else "",
                        "usage_metadata": {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": 0,
                        },
                    }
            return parsed_result

        except KeyError as e:
            logger.error(f"KeyError when parsing LLM result: missing key {str(e)}")
            raise

        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Unexpected error when parsing LLM result: {tb_str}")
            raise


class GPTAnswerer:
    """
    Class for processing resume questions and generating answers using LLM.
    The class includes methods for processing and determining resume sections such as
    personal information, work experience, etc., based on provided questions.
    Designed for automating resume question responses,
    as well as writing cover letters.
    """

    def __init__(self, llm_api_key: str = None, llm_proxy: str = None, llm_api_url: str = None):
        self.job = None
        self.job_readable = ""
        self.current_job_context = {"job_url": "", "job_title": "", "company_name": ""}
        self.job_llm_time_seconds: Dict[str, float] = {}
        self._job_llm_lock = threading.Lock()
        self.linkedin_message_preferences: Dict[str, Any] = {}
        self.ai_adapter = AIAdapter(llm_api_key, llm_proxy, llm_api_url)
        self.llm_cheap = LoggerChatModel(
            self.ai_adapter,
            context_provider=self._get_llm_context,
            call_listener=self._record_llm_call,
        )
        self.resume_template_dir = Path(RESUME_DIR) / "templates"
        self.chains = {
            "parse_resume": self._create_pydantic_chain(
                prompts.parse_resume_template, ResumeStructure
            ),
            "resume_improvement": self._create_chain(prompts.resume_improve),
            "extract_skills_from_vacancy": self._create_chain(prompts.extract_skills_from_vacancy),
            "summarize_job_description": self._create_chain(prompts.summarize_prompt_template),
            "job_is_interesting": self._create_chain(prompts.job_is_interesting),
            "date_question": self._create_chain(prompts.date_question_template),
            "text_question": self._create_chain(prompts.text_question_answer_template),
            "numeric_question": self._create_chain(prompts.numeric_question_template),
            "text_question_with_error": self._create_chain(
                prompts.text_question_with_error_template
            ),
            "prompt_cover_letter": self._create_chain(prompts.coverletter_template),
            "linkedin_message_reply": self._create_chain(prompts.linkedin_message_reply_template),
            "linkedin_message_reply_humanizer": self._create_chain(
                prompts.linkedin_message_reply_humanizer_template
            ),
            "prompt_header": self._create_chain(prompts.prompt_header),
            "prompt_education": self._create_chain(prompts.prompt_education),
            "prompt_working_experience": self._create_chain(prompts.prompt_working_experience),
            "prompt_side_projects": self._create_chain(prompts.prompt_side_projects),
            "prompt_achievements": self._create_chain(prompts.prompt_achievements),
            "prompt_certifications": self._create_chain(prompts.prompt_certifications),
            "prompt_additional_skills": self._create_chain(prompts.prompt_additional_skills),
            "linkedin_message_classification": self._create_pydantic_chain(
                prompts.linkedin_message_classification_template,
                LinkedInMessageClassification,
            ),
            "generate_resume_text": self._create_chain(prompts.generate_resume_text_template),
        }

    @staticmethod
    def find_best_match(text: str, options: list[str]) -> str:
        """
        Find the best match for a string with one of the options
        and return the best option from the list.
        """
        if "no info" in text.lower():
            return "no info"
        if not options:
            return "no info"
        logger.info(f"Searching for best match for text: '{text}' in options: {options}")
        text_lower = text.lower()
        for option in options:
            if text_lower == option.lower():
                logger.info(f"Best match found: {option}")
                return option
        for option in options:
            if text_lower in option.lower() or option.lower() in text_lower:
                logger.info(f"Best match found: {option}")
                return option
        logger.info(f"No match found for '{text}' in options, returning no info")
        return "no info"

    @staticmethod
    def _remove_placeholders(text: str) -> str:
        """Remove all 'PLACEHOLDER' placeholders from text."""
        logger.debug("Removing placeholders from text")
        return text.replace("PLACEHOLDER", "").strip()

    @staticmethod
    def _preprocess_template_string(template: str) -> str:
        """Transform template string for use in prompts."""
        logger.debug("Preprocessing template string")
        return textwrap.dedent(template)

    @staticmethod
    def _clean_html_response(html_response: str) -> str:
        """Clean HTML response by removing markdown code block wrappers"""
        # Remove markdown code block wrappers
        html_response = html_response.strip()

        # Remove ```html at the beginning
        if html_response.startswith("```html"):
            html_response = html_response[7:]  # Remove "```html"

        # Remove ``` at the end
        if html_response.endswith("```"):
            html_response = html_response[:-3]  # Remove "```"

        # Remove any remaining ```html patterns that might be in the middle
        html_response = html_response.replace("```html", "").replace("```", "")

        return html_response.strip()

    def set_resume(self, resume_structured: Dict[str, Any], resume_readable: str) -> None:
        """Add resume for analysis."""
        logger.info("Adding resume")
        self.resume_structured = resume_structured
        if not self.resume_structured["personal_information"].get("phone_code"):
            phone_prefix = self.resume_structured["personal_information"].get("phone_prefix", "")
            if phone_prefix:
                self.resume_structured["personal_information"]["phone_code"] = phone_prefix
        self.resume_readable = resume_readable

    def set_linkedin_message_preferences(self, preferences: Dict[str, Any] | None) -> None:
        self.linkedin_message_preferences = preferences or {}

    def _set_current_job_context(self, job: Dict[str, Any] | None) -> None:
        if not job:
            self.current_job_context = {"job_url": "", "job_title": "", "company_name": ""}
            return

        job_url = str(job.get("url") or "")
        self.current_job_context = {
            "job_url": job_url,
            "job_title": job.get("job_title") or job.get("title") or "",
            "company_name": job.get("company_name") or "",
        }
        if job_url:
            with self._job_llm_lock:
                self.job_llm_time_seconds.setdefault(job_url, 0.0)

    def _get_llm_context(self) -> Dict[str, str]:
        return dict(self.current_job_context)

    def _record_llm_call(
        self,
        response_time_seconds: float,
        parsed_reply: Dict[str, Dict],
        context: Dict[str, str] | None = None,
    ) -> None:
        job_context = context or {}
        job_url = job_context.get("job_url", "")
        if not job_url:
            return

        with self._job_llm_lock:
            total_time = self.job_llm_time_seconds.get(job_url, 0.0) + response_time_seconds
            self.job_llm_time_seconds[job_url] = total_time

        emit_event(
            "llm_call_completed",
            f"LLM call completed for {job_context.get('job_title') or 'job'}",
            url=job_url,
            job_title=job_context.get("job_title"),
            company_name=job_context.get("company_name"),
            response_time_seconds=round(response_time_seconds, 3),
            total_job_llm_time_seconds=round(total_time, 3),
            input_tokens=parsed_reply.get("usage_metadata", {}).get("input_tokens", 0),
            output_tokens=parsed_reply.get("usage_metadata", {}).get("output_tokens", 0),
            total_tokens=parsed_reply.get("usage_metadata", {}).get("total_tokens", 0),
            model_name=parsed_reply.get("response_metadata", {}).get("model_name", ""),
        )

    def get_job_llm_time_seconds(self, job_url: str) -> float:
        with self._job_llm_lock:
            return round(self.job_llm_time_seconds.get(job_url, 0.0), 3)

    def set_job(self, job: Dict[str, Any], is_test: bool = False) -> None:
        """Add job description."""
        self.job = job
        self._set_current_job_context(job)
        text = transform_vacancy_data(job)
        if is_test:
            self.job_readable = text
        else:
            self.job_readable = self.summarize_job_description(text)
        logger.info(f"Adding job description: {self.job_readable}")

    def set_search_parameters(self, parameters: dict) -> None:
        """Set job search parameters."""
        logger.info(f"Setting job search parameters: {parameters}")
        self.search_parameters = transform_search_config_data(parameters)

    def _create_chain(self, template: str) -> ChatPromptTemplate:
        """Create a chain for a specific resume section."""
        template = self._preprocess_template_string(template)
        prompt = ChatPromptTemplate.from_template(template)
        return prompt | self.llm_cheap | StrOutputParser()

    def _create_pydantic_chain(
        self, template: str, pydantic_object: BaseModel
    ) -> Tuple[ChatPromptTemplate, PydanticOutputParser]:
        """Create a chain for a specific resume section."""
        parser = PydanticOutputParser(pydantic_object=pydantic_object)
        template = self._preprocess_template_string(template)
        prompt = ChatPromptTemplate.from_template(template)
        return prompt | self.llm_cheap | parser, parser

    @staticmethod
    def _stringify_linkedin_conversation(conversation: Dict[str, Any]) -> str:
        lines = []
        for key, label in [
            ("participant_name", "Participant"),
            ("participant_headline", "Headline"),
            ("timestamp", "Conversation timestamp"),
            ("snippet", "Inbox snippet"),
            ("last_sender", "Last sender"),
        ]:
            value = conversation.get(key)
            if value:
                lines.append(f"{label}: {value}")

        messages = conversation.get("messages") or []
        if messages:
            lines.append("Messages:")
            for message in messages:
                sender = message.get("sender") or "Unknown"
                timestamp = message.get("timestamp") or ""
                body = message.get("body") or ""
                lines.append(f"- {sender} [{timestamp}]: {body}")

        return "\n".join(lines) if lines else "No conversation details available."

    @staticmethod
    def _build_apology_context(
        conversation: Dict[str, Any],
        classification: Dict[str, Any] | None = None,
        preferences: Dict[str, Any] | None = None,
    ) -> str:
        from datetime import datetime

        preferences = preferences or {}
        if not preferences.get("old_message_apology_enabled", True):
            return ""

        timestamp_str = conversation.get("timestamp", "")
        if not timestamp_str:
            return ""

        months = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }
        parts = timestamp_str.strip().split()
        if len(parts) < 2:
            return ""

        month_part = parts[0].lower()[:3]
        day_part = parts[1].rstrip(",")
        if month_part not in months or not day_part.isdigit():
            return ""

        now = datetime.now()
        msg_month = months[month_part]
        msg_day = int(day_part)
        # LinkedIn spells the year out only on messages from an earlier year
        # ("Aug 9, 2025"); without it the message belongs to the last 12 months
        year_part = parts[2].strip(",") if len(parts) > 2 else ""
        if len(year_part) == 4 and year_part.isdigit():
            msg_year = int(year_part)
        else:
            msg_year = now.year
            if msg_month > now.month:
                msg_year -= 1

        msg_date = datetime(msg_year, msg_month, msg_day)
        age_days = (now - msg_date).days
        threshold_days = max(int(preferences.get("old_message_threshold_days", 60)), 1)
        if age_days < threshold_days:
            return ""

        category = (classification or {}).get("category")
        apology_reason = (
            preferences.get("old_message_apology_reason")
            or "you've been busy with multiple projects"
        ).strip()
        follow_up_enabled = preferences.get("old_job_message_follow_up_enabled", True)
        follow_up_text = (
            (
                preferences.get("old_job_message_follow_up_text")
                or "ask if the opportunity is still available"
            )
            .strip()
            .rstrip(".")
        )
        if category != "job_offer_to_me":
            return (
                f"- This message was sent over {threshold_days} days ago. Start the reply with a brief, warm "
                f"apology for the late response, explaining {apology_reason}.\n"
            )

        follow_up_instruction = ""
        if follow_up_enabled and follow_up_text:
            follow_up_instruction = f" Then politely {follow_up_text}."

        return (
            f"- This message was sent over {threshold_days} days ago. Start the reply with a brief, warm "
            f"apology for the late response, explaining {apology_reason}.{follow_up_instruction}\n"
        )

    def _linkedin_reply_tone(self) -> str:
        return self.linkedin_message_preferences.get(
            "reply_tone",
            "a thoughtful senior engineering leader",
        )

    def _linkedin_reply_max_characters(self) -> int:
        return max(int(self.linkedin_message_preferences.get("reply_max_characters", 600)), 1)

    def _linkedin_reply_paragraph_instruction(self) -> str:
        if self.linkedin_message_preferences.get("reply_short_paragraphs", True):
            return "Break the reply into short paragraphs (2-3 sentences each) separated by blank lines. One big block of text looks robotic."
        return "Use the number of paragraphs that reads most naturally for the message."

    def _linkedin_reply_punctuation_instruction(self) -> str:
        if self.linkedin_message_preferences.get("reply_avoid_em_dash", True):
            return 'Never use em dashes ("—"). Use commas, periods, or separate sentences instead.'
        return "Use natural punctuation that fits the message."

    def parse_resume(self, resume_text: str) -> Dict[str, Any]:
        """Parse resume using Pydantic models for structured output."""
        logger.info("Parsing resume with structured output")
        chain, parser = self.chains["parse_resume"]
        output = chain.invoke(
            {"resume": resume_text, "format_instructions": parser.get_format_instructions()}
        )
        logger.debug(f"Structured resume parsing completed: {output}")
        return output.model_dump()

    def generate_resume_text(self, raw_text: str, template: str) -> str:
        """Generate formatted resume_text.txt content from raw PDF text using the given template."""
        logger.info("Generating resume text from raw PDF content")
        chain = self.chains["generate_resume_text"]
        return chain.invoke({"raw_text": raw_text, "template": template})

    def extract_skills_from_vacancy(self, job_description: str) -> list[str]:
        """Extract skills from vacancy"""
        chain = self.chains["extract_skills_from_vacancy"]
        output = chain.invoke({"job_description": job_description})
        output = output.replace("[", "").replace("]", "")
        output = output.replace("'", "").replace('"', "")
        output = output.split(",")
        output = [skill.strip() for skill in output if skill.strip()]
        logger.debug(f"Skills extracted from vacancy: {output}")
        return output

    def summarize_job_description(self, text: str) -> str:
        """Create brief job description"""
        logger.info(f"Creating brief job description: '{text}'")
        chain = self.chains["summarize_job_description"]
        output = chain.invoke({"text": text})
        logger.debug(f"Generated brief description: {output}")
        return output

    def answer_question_date(self, question: str, previous_questions: list[str]) -> str:
        """Answer a date question and return the result in MM/DD/YYYY format"""
        current_date = datetime.now().date().strftime("%Y-%m-%d")
        chain = self.chains["date_question"]
        output = chain.invoke(
            {
                "resume": self.resume_readable,
                "question": question,
                "current_date": current_date,
                "previous_questions": previous_questions,
            }
        )
        logger.debug(f"Date answer: {output}")
        return output.strip()

    def answer_question_textual_wide_range(
        self, question: str, previous_questions: list[str]
    ) -> str:
        """Determine the topic of the given question and answer it"""
        current_date = datetime.now().date().strftime("%Y-%m-%d")
        gender = self.resume_structured["personal_information"].get("gender")
        chain = self.chains["text_question"]
        output = chain.invoke(
            {
                "resume": self.resume_readable,
                "question": question,
                "current_date": current_date,
                "gender": gender,
                "previous_questions": previous_questions,
            }
        )
        logger.debug(f"Answer to question: {output}")
        return output

    def answer_question_textual_wide_range_with_error(
        self, question: str, error: str, previous_answer: str, previous_questions: list[str]
    ) -> str:
        """Answer question with error"""
        current_date = datetime.now().date().strftime("%Y-%m-%d")
        chain = self.chains["text_question_with_error"]
        output = chain.invoke(
            {
                "resume": self.resume_readable,
                "question": question,
                "previous_answer": previous_answer,
                "error": error,
                "current_date": current_date,
                "previous_questions": previous_questions,
            }
        )
        logger.debug(f"Answer to question with error: {output}")
        return output

    def answer_question_numeric(self, question: str, previous_questions: list[str]) -> str:
        """Answer numeric question"""
        question_lower = question.lower()
        if any(
            keyword in question_lower
            for keyword in ["phone", "mobile", "telephone", "contact number"]
        ):
            phone = self.resume_structured["personal_information"].get("phone", "")
            phone_code = self.resume_structured["personal_information"].get("phone_code", "")
            if phone:
                phone_value = f"{phone_code} {phone}".strip()
                phone_digits = re.sub(r"\D", "", phone_value)
                if phone_digits:
                    logger.info(
                        "Answered phone question using structured resume: %s",
                        phone_digits,
                    )
                    return phone_digits

        current_date = datetime.now().date().strftime("%Y-%m-%d")

        chain = self.chains["numeric_question"]
        output = chain.invoke(
            {
                "resume": self.resume_readable,
                "question": question,
                "current_date": current_date,
                "previous_questions": previous_questions,
            }
        )
        logger.debug(f"Raw output for numeric question: {output}")
        if output.lower() == "no info":
            return output
        try:
            output = self._extract_number_from_string(output)
        except ValueError:
            logger.warning(
                "LLM returned a non-numeric answer for numeric question '%s': %s",
                question,
                output,
            )
            return "no info"
        logger.info(f"Extracted number: {output}")
        return output

    def _extract_number_from_string(self, output_str: str) -> str:
        """Extract number from string"""
        stripped = output_str.strip()
        # If the output looks like a phone number or other formatted number
        # (starts with + or digit and contains only digits/spaces/hyphens/parens),
        # return all digits concatenated to preserve the full value.
        if len(stripped) > 1 and re.match(r"^[+\d][\d\s\-().]*$", stripped):
            all_digits = re.sub(r"\D", "", stripped)
            if all_digits:
                return all_digits
        # Match salary ranges like $60000-$80000, £280-£560, or $60,000-$80,000
        range_match = re.search(r"[^\d,]?([\d,]+)\s*-\s*[^\d,]?([\d,]+)", output_str)
        if range_match:
            low = range_match.group(1).replace(",", "")
            high = range_match.group(2).replace(",", "")
            return f"{low}-{high}"
        numbers = re.findall(r"\d+", output_str)
        if numbers:
            return str(numbers[0])
        else:
            logger.error("No numbers found in the string")
            raise ValueError("No numbers found in the string")

    def select_one_answer_from_options(
        self, question: str, options: list[str], previous_questions: list[str]
    ) -> str:
        """
        Ask LLM a question with one answer option.
        Return the best option.
        """
        gender = self.resume_structured["personal_information"]["gender"]
        func_template = self._preprocess_template_string(prompts.options_template)
        prompt = ChatPromptTemplate.from_template(func_template)
        chain = prompt | self.llm_cheap | StrOutputParser()
        output_str = chain.invoke(
            {
                "resume": self.resume_readable,
                "question": question,
                "options": options,
                "gender": gender,
                "previous_questions": previous_questions,
            }
        )
        logger.debug(f"LLM response: {output_str}")
        best_option = self.find_best_match(output_str, options)
        if best_option.lower() != "no info":
            logger.info(f"Best option found: {best_option}")
        return best_option

    def select_many_answers_from_options(
        self, question: str, options: list[str], previous_questions: list[str]
    ) -> List[str]:
        """
        Ask LLM a question with one or more answer options.
        Return a list of best options.
        """
        logger.info(f"Asking question: {question}")
        logger.info(f"Available options: {options}")
        gender = self.resume_structured["personal_information"]["gender"]
        func_template = self._preprocess_template_string(prompts.many_options_template)
        prompt = ChatPromptTemplate.from_template(func_template)
        chain = prompt | self.llm_cheap | StrOutputParser()
        output_str = chain.invoke(
            {
                "resume": self.resume_readable,
                "question": question,
                "options": options,
                "gender": gender,
                "previous_questions": previous_questions,
            }
        )
        logger.debug(f"LLM response: {output_str}")
        # in case LLM returns a python-like list
        output_str = output_str.replace("[", "").replace("]", "")
        output_str = output_str.replace("'", "").replace("'", "")
        outputs = output_str.split(";")
        best_options = []
        for output in outputs:
            best_option = self.find_best_match(output, options)
            best_options.append(best_option)
        logger.info(f"Best options: {best_options}")
        return best_options

    def job_is_interesting(self, job: Dict[str, Any]) -> bool | None:
        """
        Ask LLM if the job is interesting with our resume, skills and interests.
        Return True if the job is interesting, False otherwise.
        """
        chain = self.chains["job_is_interesting"]
        job_description = transform_vacancy_data(job)
        self._set_current_job_context(job)
        try:
            output = chain.invoke(
                {
                    "resume": self.resume_readable,
                    "job_description": job_description,
                    "search_parameters": self.search_parameters,
                }
            )
        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Error calling LLM\n{tb_str}")
            return None
        logger.debug(f"LLM response: '{output}'")
        # parse the LLM response
        try:
            score = re.search(r"Score: (\d+)", output).group(1)
            reasoning = re.search(r"Reasoning: (.+)", output, re.DOTALL).group(1)
        except AttributeError:
            logger.error(f"LLM returned an incorrect response:\n{output}")
            return False
        logger.info(f"Job interest score: {score}")
        if int(score) < JOB_IS_INTERESTING_THRESH:
            logger.info(f"Job is not interesting: {reasoning}")
            return False, score, reasoning
        return True, score, reasoning

    def write_cover_letter(self) -> str:
        """
        Create a cover letter based on the resume and job description.
        Return the text of the cover letter.
        """
        # depending on the availability of the contact, set it in the prompt
        logger.info("Writing cover letter")
        phone = self.resume_structured["personal_information"].get("phone", "")
        phone_code = self.resume_structured["personal_information"].get("phone_code", "")
        email = self.resume_structured["personal_information"].get("email", "")
        additional_prompt = "- Specify the following contacts: "
        invoke_dict = {
            "resume": self.resume_readable,
            "company_name": (
                self.job.get("company_name", "")
                if isinstance(self.job, dict)
                else self.job.company_name
            ),
            "job_description": self.job_readable,
        }
        if phone:
            additional_prompt += f"Phone: {phone_code} {phone}\n"
            invoke_dict["phone"] = f"{phone_code} {phone}"
        if email:
            additional_prompt += f"Email: {email}\n"
            invoke_dict["email"] = email

        chain = self.chains["prompt_cover_letter"]
        output = chain.invoke(invoke_dict)
        logger.debug(f"Cover letter generated: {output}")
        return output

    def classify_linkedin_message(self, conversation: Dict[str, Any]) -> Dict[str, Any]:
        """Classify a LinkedIn conversation for dry-run inbox triage."""
        chain, parser = self.chains["linkedin_message_classification"]
        conversation_text = self._stringify_linkedin_conversation(conversation)
        try:
            output = chain.invoke(
                {
                    "resume": self.resume_readable,
                    "conversation": conversation_text,
                    "format_instructions": parser.get_format_instructions(),
                }
            )
            return output.model_dump()
        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Error classifying LinkedIn message conversation\n{tb_str}")
            return {
                "category": "personal_message",
                "confidence": 0,
                "reasoning": "Classification failed, defaulting to keep for manual review.",
                "proposed_action": "keep",
            }

    def draft_linkedin_message_reply(
        self, conversation: Dict[str, Any], classification: Dict[str, Any]
    ) -> str:
        """Draft a reply for an important LinkedIn conversation."""
        draft_chain = self.chains["linkedin_message_reply"]
        humanizer_chain = self.chains["linkedin_message_reply_humanizer"]
        conversation_text = self._stringify_linkedin_conversation(conversation)
        apology_context = self._build_apology_context(
            conversation,
            classification,
            self.linkedin_message_preferences,
        )
        try:
            output = draft_chain.invoke(
                {
                    "resume": self.resume_readable,
                    "classification": classification,
                    "conversation": conversation_text,
                    "apology_context": apology_context,
                    "reply_tone": self._linkedin_reply_tone(),
                    "reply_max_characters": self._linkedin_reply_max_characters(),
                    "reply_paragraph_instruction": self._linkedin_reply_paragraph_instruction(),
                    "reply_punctuation_instruction": self._linkedin_reply_punctuation_instruction(),
                }
            )
        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Error drafting LinkedIn message reply\n{tb_str}")
            return ""

        try:
            humanized = humanizer_chain.invoke(
                {
                    "reply": output.strip(),
                    "reply_paragraph_instruction": self._linkedin_reply_paragraph_instruction(),
                    "reply_punctuation_instruction": self._linkedin_reply_punctuation_instruction(),
                }
            )
            return humanized.strip() or output.strip()
        except Exception:
            tb_str = traceback.format_exc()
            logger.error(f"Error humanizing LinkedIn message reply\n{tb_str}")
            return output.strip()

    def resume_improvement_recommendations(self) -> str:
        """
        Write resume improvement recommendations
        """
        logger.info("Writing resume improvement recommendations")
        chain = self.chains["resume_improvement"]
        output = chain.invoke(
            {
                "resume": self.resume_readable,
            }
        )
        logger.debug(f"Resume improvement recommendations generated: {output}")
        return output

    def generate_header(self) -> str:
        """Generating resume header"""
        logger.info("Generating resume header")
        chain = self.chains["prompt_header"]

        output = chain.invoke(
            {
                "personal_information": self.resume_structured["personal_information"],
            }
        )
        logger.debug(f"Header generated: {output}")
        cleaned_output = self._clean_html_response(output)
        logger.info("Resume header generated")
        return cleaned_output

    def generate_education_section(self) -> str:
        """Generating education section for resume"""
        logger.info("Generating education section for resume")
        chain = self.chains["prompt_education"]
        output = chain.invoke(
            {
                "education_details": self.resume_structured["education_details"],
                "job_description": self.job_readable,
            }
        )
        logger.debug(f"Education section generated: {output}")
        cleaned_output = self._clean_html_response(output)
        logger.info("Education section generated")
        return cleaned_output

    def generate_work_experience_section(self) -> str:
        """Generating work experience section for resume"""
        logger.info("Generating work experience section for resume")
        chain = self.chains["prompt_working_experience"]
        output = chain.invoke(
            {
                "experience_details": self.resume_structured["experience_details"],
                "job_description": self.job_readable,
            }
        )
        logger.debug(f"Work experience section generated: {output}")
        cleaned_output = self._clean_html_response(output)
        logger.info("Work experience section generated")
        return cleaned_output

    def generate_side_projects_section(self) -> str:
        """Generating side projects section for resume"""
        logger.info("Generating side projects section for resume")
        chain = self.chains["prompt_side_projects"]
        output = chain.invoke(
            {
                "projects": self.resume_structured["projects"],
                "job_description": self.job_readable,
            }
        )
        logger.debug(f"Side projects section generated: {output}")
        cleaned_output = self._clean_html_response(output)
        logger.info("Side projects section generated")
        return cleaned_output

    def generate_achievements_section(self) -> str:
        """Generating achievements section for resume"""
        logger.info("Generating achievements section for resume")
        chain = self.chains["prompt_achievements"]
        input_data = {
            "achievements": self.resume_structured["achievements"],
            "job_description": self.job_readable,
        }

        output = chain.invoke(input_data)
        logger.debug(f"Achievements section generated: {output}")
        cleaned_output = self._clean_html_response(output)
        logger.info("Achievements section generated")
        return cleaned_output

    def generate_certifications_section(self) -> str:
        """Generate certifications section for resume"""
        logger.info("Generating certifications section for resume")
        chain = self.chains["prompt_certifications"]
        input_data = {
            "certifications": self.resume_structured["certifications"],
            "job_description": self.job_readable,
        }

        output = chain.invoke(input_data)
        logger.debug(f"Certifications section generated: {output}")
        cleaned_output = self._clean_html_response(output)
        logger.info("Certifications section generated")
        return cleaned_output

    def generate_additional_skills_section(self) -> str:
        """Generate skills section for resume"""
        logger.info("Generating additional skills section for resume")

        chain = self.chains["prompt_additional_skills"]
        output = chain.invoke(
            {
                "languages": self.resume_structured["languages"],
                "skills": self.resume_structured["skills"],
                "interests": self.resume_structured["interests"],
                "job_description": self.job_readable,
            }
        )
        logger.debug(f"Additional skills section generated: {output}")
        cleaned_output = self._clean_html_response(output)
        logger.info("Additional skills section generated")
        return cleaned_output

    def generate_html_resume(self) -> str:
        """Creating a resume from generated components"""

        def header_fn():
            template_resume = self.load_resume_template("header")
            if template_resume:
                return template_resume
            if self.resume_structured["personal_information"] and self.job_readable:
                header = self.generate_header()
                self.save_resume_template("header", header)
                return header
            return ""

        def education_fn():
            if self.resume_structured["education_details"] and self.job_readable:
                return self.generate_education_section()
            return ""

        def work_experience_fn():
            if self.resume_structured["experience_details"] and self.job_readable:
                return self.generate_work_experience_section()
            return ""

        def side_projects_fn():
            if self.resume_structured["projects"] and self.job_readable:
                return self.generate_side_projects_section()
            return ""

        def achievements_fn():
            if self.resume_structured["achievements"] and self.job_readable:
                return self.generate_achievements_section()
            return ""

        def certifications_fn():
            if self.resume_structured["certifications"] and self.job_readable:
                return self.generate_certifications_section()
            return ""

        def additional_skills_fn():
            if (
                self.resume_structured["experience_details"]
                or self.resume_structured["education_details"]
                or self.resume_structured["languages"]
                or self.resume_structured["interests"]
                or self.resume_structured["skills"]
                or self.resume_structured["about_me"]
            ) and self.job_readable:
                return self.generate_additional_skills_section()
            return ""

        # Create a dictionary to map the function names to their respective callables
        functions = {
            "header": header_fn,
            "education": education_fn,
            "work_experience": work_experience_fn,
            "side_projects": side_projects_fn,
            "achievements": achievements_fn,
            "certifications": certifications_fn,
            "additional_skills": additional_skills_fn,
        }

        # Use ThreadPoolExecutor to run the functions in parallel
        with ThreadPoolExecutor() as executor:
            future_to_section = {executor.submit(fn): section for section, fn in functions.items()}
            results = {}
            for future in as_completed(future_to_section):
                section = future_to_section[future]
                try:
                    result = future.result()
                    if result:
                        results[section] = result
                except Exception:
                    tb_str = traceback.format_exc()
                    logger.error(f"Section {section} processed with an error\n{tb_str}")
        full_resume = "<body>\n"
        full_resume += f"  {results.get('header', '')}\n"
        full_resume += "  <main>\n"
        full_resume += f"    {results.get('education', '')}\n"
        full_resume += f"    {results.get('work_experience', '')}\n"
        full_resume += f"    {results.get('side_projects', '')}\n"
        full_resume += f"    {results.get('achievements', '')}\n"
        full_resume += f"    {results.get('certifications', '')}\n"
        full_resume += f"    {results.get('additional_skills', '')}\n"
        full_resume += "  </main>\n"
        full_resume += "</body>"
        return full_resume

    def load_resume_template(self, template_name: str) -> str:
        """Load template resume"""
        if not self.resume_template_dir.exists():
            self.resume_template_dir.mkdir(parents=True)
        try:
            with open(
                self.resume_template_dir / f"{template_name}.html", "r", encoding="utf-8"
            ) as f:
                resume_template = f.read()
                return resume_template
        except FileNotFoundError:
            return ""

    def save_resume_template(self, template_name: str, resume_template: str) -> None:
        """Save template resume"""
        with open(self.resume_template_dir / f"{template_name}.html", "w", encoding="utf-8") as f:
            f.write(resume_template)


if __name__ == "__main__":
    import yaml

    load_dotenv()
    api_key = os.getenv("llm_api_key", "")
    llm_proxy = os.getenv("llm_proxy", "")
    llm_api_url = os.getenv("llm_api_url", None)

    resume_dir = Path(RESUME_DIR)
    resume_text_path = resume_dir / "resume_text.txt"
    resume_structured_path = resume_dir / "structured_resume.yaml"

    with open(resume_text_path, "r", encoding="utf-8") as f:
        resume_text = f.read()

    with open(resume_structured_path, "r", encoding="utf-8") as f:
        resume_structured = yaml.safe_load(f)
    resume_structured = ResumeStructure(**resume_structured).model_dump()

    answerer = GPTAnswerer(llm_api_key=api_key, llm_proxy=llm_proxy, llm_api_url=llm_api_url)
    answerer.set_resume(resume_structured, resume_text)

    test_cases = [
        {
            "type": "textual",
            "question": "Tell me about your educational background.",
        },
        {
            "type": "numeric",
            "question": "How many years of experience do you have with Python?",
        },
        {
            "type": "numeric",
            "question": "What are your salary expectations (annual, USD)?",
        },
        {
            "type": "numeric",
            "question": "What are your salary expectations (monthly, EUR)?",
        },
        {
            "type": "numeric",
            "question": "What are your salary expectations (daily, GBP)?",
        },
        {
            "type": "radio",
            "question": "What is your highest level of education?",
            "options": ["High School", "Bachelor's Degree", "Master's Degree", "PhD"],
        },
        {
            "type": "checkbox",
            "question": "Which of the following programming languages are you proficient in?",
            "options": ["Python", "Java", "C++", "JavaScript", "Go", "Rust"],
        },
    ]

    for case in test_cases:
        print(f"\n{'=' * 60}")
        print(f"Type: {case['type']}")
        print(f"Question: {case['question']}")
        if "options" in case:
            print(f"Options: {case['options']}")
        print("-" * 60)

        q = case["question"]
        if case["type"] == "textual":
            answer = answerer.answer_question_textual_wide_range(q, [])
        elif case["type"] == "numeric":
            answer = answerer.answer_question_numeric(q, [])
        elif case["type"] == "radio":
            answer = answerer.select_one_answer_from_options(q, case["options"], [])
        elif case["type"] == "checkbox":
            answer = answerer.select_many_answers_from_options(q, case["options"], [])

        print(f"Answer: {answer}")
