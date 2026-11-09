# Dummy personal data for anonymization (male)
DUMMY_PERSONAL_INFO_MALE = {
    "name": "Zorquill Thalaorix",
    "first_name": "Zorquill",
    "last_name": "Thalaorix",
    "last_name_2": "Thalaris",
    # "birthday": "03.05.1993",
    "phone": "9335753535",
    "email": "zorquill_thalaorix@gmail.com",
    "linkedin": "https://linkedin.com/in/zorquill_thalaorix-f3e57c712",
    "github": "https://github.com/zorquill_thalaorix",
    "zip_code": "09876",
    "address": "1234 Imaginary Lane",
}

# Dummy personal data for anonymization (female)
DUMMY_PERSONAL_INFO_FEMALE = {
    "name": "Zorquillia Thalaorix",
    "first_name": "Zorquillia",
    "last_name": "Thalaorix",
    "last_name_2": "Thalaris",
    # "birthday": "03.05.1993",
    "phone": "9335753535",
    "email": "zorquillia_thalaorix@gmail.com",
    "linkedin": "https://linkedin.com/in/zorquillia_thalaorix-f3e57c712",
    "github": "https://github.com/zorquillia_thalaorix",
    "zip_code": "09876",
    "address": "1234 Imaginary Lane",
}

# Paths to log files and settings
SEARCH_CONFIG_FILE = "config/search_config.yaml"
OUTPUT_DIR_LINKEDIN = "data/output/linkedin"
OUTPUT_DIR_INDEED = "data/output/indeed"
DEBUG_DIR = "data/debug"
LOG_DIR = "logs"
RESUME_DIR = "data/resumes"
PHOTO_DIR = "data/photo"
COVER_LETTER_DIR = "data/cover_letters"
BROWSER_STORAGE_STATE = "browser_session/browser_state.json"
RESUME_TEXT_TEMPLATE_FILE = "examples/data/resumes/resume_text.txt"
APP_CONFIG_FILE = "config/app_config.yaml"

# Default cost per token fallback when model is not in PRICE_DICT
CUSTOM_COST_PER_TOKEN = {
    "input_cost_per_token": 0.25 / 1_000_000,
    "output_cost_per_token": 1.50 / 1_000_000,
}

# Per-model token pricing (input/output cost per token in USD)
PRICE_DICT: dict[str, dict[str, float]] = {
    # Gemini
    "gemini-3.1-flash-lite-preview": {
        "input_cost_per_token": 0.25 / 1_000_000,
        "output_cost_per_token": 1.50 / 1_000_000,
    },
    "gemini-3-flash-preview": {
        "input_cost_per_token": 0.15 / 1_000_000,
        "output_cost_per_token": 0.60 / 1_000_000,
    },
    "gemini-3.8-flash": {
        "input_cost_per_token": 0.825 / 1_000_000,
        "output_cost_per_token": 4.125 / 1_000_000,
    },
    # OpenAI
    "gpt-4o-mini": {
        "input_cost_per_token": 0.15 / 1_000_000,
        "output_cost_per_token": 0.60 / 1_000_000,
    },
    "gpt-4o": {
        "input_cost_per_token": 2.50 / 1_000_000,
        "output_cost_per_token": 10.00 / 1_000_000,
    },
    "gpt-5-mini": {
        "input_cost_per_token": 0.15 / 1_000_000,
        "output_cost_per_token": 0.60 / 1_000_000,
    },
    "gpt-5-nano": {
        "input_cost_per_token": 0.10 / 1_000_000,
        "output_cost_per_token": 0.40 / 1_000_000,
    },
    # Anthropic
    "anthropic/claude-haiku-4-5": {
        "input_cost_per_token": 0.80 / 1_000_000,
        "output_cost_per_token": 4.00 / 1_000_000,
    },
    "anthropic/claude-haiku-5.5": {
        "input_cost_per_token": 0.10 / 1_000_000,
        "output_cost_per_token": 0.50 / 1_000_000,
    },
    "anthropic/claude-sonnet-4": {
        "input_cost_per_token": 3.00 / 1_000_000,
        "output_cost_per_token": 15.00 / 1_000_000,
    },
    "anthropic/claude-sonnet-4-5": {
        "input_cost_per_token": 3.00 / 1_000_000,
        "output_cost_per_token": 15.00 / 1_000_000,
    },
    "anthropic/claude-sonnet-4-6": {
        "input_cost_per_token": 3.00 / 1_000_000,
        "output_cost_per_token": 15.00 / 1_000_000,
    },
    # DeepSeek
    "deepseek/deepseek-chat-v3.1": {
        "input_cost_per_token": 0.15 / 1_000_000,
        "output_cost_per_token": 0.75 / 1_000_000,
    },
    "deepseek/deepseek-chat-v3.2": {
        "input_cost_per_token": 0.26 / 1_000_000,
        "output_cost_per_token": 0.38 / 1_000_000,
    },
    "deepseek/deepseek-v4-flash": {
        "input_cost_per_token": 0.14 / 1_000_000,
        "output_cost_per_token": 0.28 / 1_000_000,
    },
    # Qwen
    "qwen/qwen3.5-flash-02-23": {
        "input_cost_per_token": 0.065 / 1_000_000,
        "output_cost_per_token": 0.26 / 1_000_000,
    },
    "qwen/qwen3.6-plus": {
        "input_cost_per_token": 0.325 / 1_000_000,
        "output_cost_per_token": 1.30 / 1_000_000,
    },
    # NVIDIA NIM
    "meta/llama-3.3-70b-instruct": {
        "input_cost_per_token": 0.27 / 1_000_000,
        "output_cost_per_token": 0.85 / 1_000_000,
    },
    "meta/llama-3.1-405b-instruct": {
        "input_cost_per_token": 1.00 / 1_000_000,
        "output_cost_per_token": 3.00 / 1_000_000,
    },
    "nvidia/llama-3.1-nemotron-70b-instruct": {
        "input_cost_per_token": 0.27 / 1_000_000,
        "output_cost_per_token": 0.85 / 1_000_000,
    },
    # Groq
    "llama-3.3-70b-versatile": {
        "input_cost_per_token": 0.59 / 1_000_000,
        "output_cost_per_token": 0.79 / 1_000_000,
    },
    "llama-3.1-8b-instant": {
        "input_cost_per_token": 0.05 / 1_000_000,
        "output_cost_per_token": 0.08 / 1_000_000,
    },
    "deepseek-r1-distill-llama-70b": {
        "input_cost_per_token": 0.75 / 1_000_000,
        "output_cost_per_token": 0.99 / 1_000_000,
    },
    # Cerebras
    "llama-3.3-70b": {
        "input_cost_per_token": 0.85 / 1_000_000,
        "output_cost_per_token": 1.20 / 1_000_000,
    },
    "llama-3.1-8b": {
        "input_cost_per_token": 0.10 / 1_000_000,
        "output_cost_per_token": 0.10 / 1_000_000,
    },
    "qwen-3-32b": {
        "input_cost_per_token": 0.45 / 1_000_000,
        "output_cost_per_token": 0.65 / 1_000_000,
    },
    # Cheaper Inference
    "deepseek-v4-flash": {
        "input_cost_per_token": 0.09 / 1_000_000,
        "output_cost_per_token": 0.36 / 1_000_000,
    },
    "glm-5.3": {
        "input_cost_per_token": 0.77 / 1_000_000,
        "output_cost_per_token": 2.42 / 1_000_000,
    },
}


def cost_per_token(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    custom_cost_per_token: dict | None = None,
) -> tuple[float, float]:
    """Return (prompt_cost, completion_cost) for the given model and token counts."""
    rates = PRICE_DICT.get(model, custom_cost_per_token or CUSTOM_COST_PER_TOKEN)
    return (
        prompt_tokens * rates["input_cost_per_token"],
        completion_tokens * rates["output_cost_per_token"],
    )
