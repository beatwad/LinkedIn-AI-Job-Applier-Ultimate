"""
This file contains application settings
"""

"""
Job site to use. Possible values: 'linkedin', 'indeed'
"""
JOB_SITE = "linkedin"

"""Maximum number of applications"""
MAX_APPLIES_NUM = 50

"""
If this mode is activated - the browser will be launched in headless mode
"""
HEADLESS_MODE = False

"""
If this mode is activated, saves screenshots and page HTML to data/debug/ on every selector failure.
Also enables Playwright tracing (saved to data/debug/trace.zip on exit, viewable at trace.playwright.dev).
No-op when False (default).
"""
DEBUG_MODE = False

"""
If this mode is activated - apply to all vacancies indiscriminately,
otherwise ask LLM to select only those vacancies that suit you
by interests or by tech stack
"""
MONKEY_MODE = False

"""
In this mode app doesn't apply to the jobs, only creates resumes, cover letters and gathers skill statistics
- resumes are created in data/resume
- cover letters are created in data/output/cover_letters
- skill statistics are gathered in data/output/skill_stat.yaml
"""
TEST_MODE = False

"""
In this mode app doesn't apply to the jobs or create resumes and cover letters, only gathers information for interesting jobs and
their skill statistics and saves them to the files data/output/interesting_jobs.yaml and data/output/skill_stat.yaml."""
COLLECT_INFO_MODE = False

"""
For Indeed only
If this setting is False, Indeed Resume will be used (no file upload).
If True, app will try to upload a resume file.
"""
UPLOAD_RESUME = True

"""
For Indeed only
The Indeed domain to search on. Use the domain of the country you actually want
results from, otherwise the search runs against the US site and returns US jobs.
Examples: "www.indeed.com" (US), "ch.indeed.com" (Switzerland),
"de.indeed.com" (Germany), "uk.indeed.com" (United Kingdom), "ca.indeed.com" (Canada)
"""
INDEED_DOMAIN = "www.indeed.com"

"""
For Indeed only
Search radius around each configured location, in the units the chosen Indeed
domain uses (miles on www.indeed.com, kilometres on most others).
Set to None to keep whatever radius Indeed applies by default.
"""
INDEED_SEARCH_RADIUS = None

"""
In this mode app applies only the jobs with Easy Apply
If this mode is deactivated, app will apply to the jobs with Easy Apply and try to apply to the jobs with 3rd party applications
WARNING: applying to the jobs with 3rd party applications is not guaranteed to be successful, but is guaranteed to consume at least 10-100x more tokens
"""
EASY_APPLY_ONLY_MODE = True

"""
If enabled for LinkedIn, ignores positions in search_config.yaml and processes
LinkedIn's recommended jobs list instead of a keyword search.
"""
LINKEDIN_RECOMMENDED_JOBS_MODE = False

"""
If enabled for LinkedIn, ignores positions in search_config.yaml and processes
LinkedIn's Top applicant picks collection instead of a keyword search.
"""
LINKEDIN_TOP_APPLICANT_JOBS_MODE = False

"""
If this mode is activated, app will check if the last search was less than a day ago.
This is useful if you want bot to automatically restart the search every 24 hours when LinkedIn resets the search limits.
"""
RESTART_EVERY_DAY = False
"""
Path to a ready-made resume PDF to use for all applications.
If empty string - a new resume is generated for each vacancy.
If set - the file at this path is used as-is for every application.
Example: data/resumes/resume.pdf
"""
READY_MADE_RESUME_PATH = ""
"""
Optional path to a photo file for LinkedIn Easy Apply image upload fields.
If empty string - the bot will try to reuse your visible LinkedIn profile photo.
"""
READY_MADE_PHOTO_PATH = ""
"""
Resume style to use for generated resumes.
If set - skips the interactive style selection prompt.
If None - prompts user to select a style interactively.
Possible values:
    - "FAANGPath"
    - "Cloyola Grey"
    - "Modern Blue"
    - "Modern Grey"
    - "Default"
    - "Clean Blue"
"""
RESUME_STYLE = None

"""
If LLM evaluated the 'interest' level of the job not below this threshold - the job is considered interesting for application.
Otherwise not.
"""
JOB_IS_INTERESTING_THRESH = 70

"""Minimum time spent on one job application"""
MINIMUM_WAIT_TIME_SEC = 10

"""
If this mode is activated, app will try to decrease RPM to avoid rate limit errors
"""
FREE_TIER = False

"""
Free tier mode wait time in seconds
"""
FREE_TIER_RPM_LIMIT = 15

"""
If this mode is activated, bot process output will be printed to the dashboard console in addition to the log file.
"""
DASHBOARD_OUTPUT_APP_LOGS = True

"""
Logging level
Possible values:
    - "DEBUG"
    - "INFO"
    - "WARNING"
    - "ERROR"
    - "CRITICAL"
"""
MINIMUM_LOG_LEVEL = "DEBUG"

"""
LLM type
Possible values:
    - "openai"
    - "gigachat"
    - "claude"
    - "ollama"
    - "gemini"
    - "huggingface"
    - "openrouter"
    - "nvidia_nim"
    - "groq"
    - "cerebras"
    - "openai_compatible"
"""
LLM_MODEL_TYPE = "openrouter"
# LLM_MODEL_TYPE = "openai"

# LLM models
EASY_APPLY_MODEL = "google/gemini-3.1-flash-lite-preview"
# EASY_APPLY_MODEL = "google/gemini-3-flash-preview"
# EASY_APPLY_MODEL = "gpt-5-mini"
APPLY_AGENT_MODEL = "google/gemini-3.1-flash-lite-preview"
# APPLY_AGENT_MODEL = "google/gemini-3-flash-preview"
# APPLY_AGENT_MODEL = "gpt-5-mini"

"""
Easy Apply model temperature
the higher it is, the more creative the model, but hallucinations may occur
the lower it is, the more strictly the model follows the prompt and invents less
"""
TEMPERATURE = 0.4
