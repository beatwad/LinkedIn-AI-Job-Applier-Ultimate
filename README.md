<p align="center">
  <img src="assets/logo.png" alt="A sample image" width="40%">
</p>

# LinkedIn AI Job Applier Ultimate

![Python](https://img.shields.io/badge/python-3.12-blue)
![License](https://img.shields.io/github/license/beatwad/LinkedIn-AI-Job-Applier-Ultimate)
![Stars](https://img.shields.io/github/stars/beatwad/LinkedIn-AI-Job-Applier-Ultimate?style=social)
![Last Commit](https://img.shields.io/github/last-commit/beatwad/LinkedIn-AI-Job-Applier-Ultimate)


🤖 AI-powered bot that **auto-applies** to jobs on **LinkedIn** and **Indeed**. It parses your resume, generates tailored resumes per vacancy, answers application questions using an LLM (Gemini, OpenAI, Claude, Ollama), gathers statistics of the most important for employers skills and delivers detailed
Telegram reports — fully automating your job search.


This is an active fork of the original [Jobs_Applier_AI_Agent_AIHawk](https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk) project, which is currently inactive. This version introduces numerous new features, bug fixes, and performance improvements.

## Disclaimer

This bot uses the LinkedIn and Indeed UIs to apply for jobs. Both sites frequently change their UI, so the bot may lose some of its functionality **at any time**.
I have no time to check this bot every day, so if you face any malfunction or have some questions about bot - feel free to open issue or contact me in Telegram chat 🚀

Please ⭐ the repository if you find it useful. This is the only thing that motivates me to continue developing the project.

## 🎥 Demo

[![LinkedIn AI Job Applier Ultimate Demo](https://img.youtube.com/vi/HmbeI8u12MU/maxresdefault.jpg)](https://www.youtube.com/watch?v=HmbeI8u12MU)

### ⚠️ Note on Indeed

Indeed support is functional but has important limitations compared to LinkedIn:

- **Most jobs are not Easy Apply.** The vast majority of Indeed listings redirect to external company websites, which the bot cannot reliably handle.
- **CAPTCHAs are frequent.** Indeed aggressively deploys CAPTCHAs that interrupt automated flows, even with bot-detection bypass techniques.
- **Sometimes Indeed is sloooow.** It can take a lot of time to apply for a job on Indeed for some users because sometimes it takes a lot of time for Indeed pages to load.

For these reasons, **LinkedIn is strongly recommended** over Indeed for automated job applications. Indeed support may improve in the future, but currently it is not well-suited for automation.

But if you're planning to use Indeed for searching jobs without auto-applying - it's a great site. You can use it for searching suitable jobs and then apply for them manually.

### LinkedIn AI Job Applier Chat 👇

[![Telegram](https://img.shields.io/badge/Telegram-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white
)](https://t.me/linkedin_auto_job)

---

## 📋 Table of Contents

- [✨ Features](#-features)
- [🚀 Getting Started](#-getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [🔧 Configuration](#-configuration)
- [▶️ Usage](#️-usage)
  - [LinkedIn Messages Manager](#linkedin-messages-manager)
  - [Dashboard](#dashboard)
  - [Dashboard Routes And APIs](#dashboard-routes-and-apis)
- [💵 Vacancy application cost](#-vacancy-application-cost)
- [✅ Running Tests](#-running-tests)
- [🐞 Troubleshooting](#-troubleshooting)
- [📨 Telegram Instruction](#-telegram-instruction)
- [🤝 Contributing](#-contributing)
- [📜 License](#-license)
- [🙏 Acknowledgements](#-acknowledgements)

---

## ✨ Features

This project enhances the original codebase with several powerful new features:

*   **🌐 Multi-Platform Support:** Applies to jobs on **LinkedIn** and **Indeed**. Switch between platforms with a single `JOB_SITE` setting in `config/app_config.py`.
*   **🌐 Universal Job Application:** Applies to **ALL** job vacancies on LinkedIn (not just Easy Apply) thanks to the [browser-use](https://github.com/browser-use/browser-use) library.
*   **🔒 Data Anonymization:** Protects your privacy by replacing personal data with mock information before sending it to the LLM provider, ensuring your sensitive information remains secure.
    *   *Note: Auto resume parsing and applying of Non-Easy Apply vacancies don't use anonymization. Additionally, country, city, and birth date are not anonymized to maintain the quality of LLM responses.*
*   **🎯 Improved Intelligent Resume Generation:** Uses AI to tailor every generated resume to the current vacancy for maximum match, adapting skills, experience, projects and achivements to the job description.
*   **🎭 Patchright Integration:** Now uses [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) (a patched build of Playwright) instead of Selenium/Playwright for faster, more reliable and undetectable browser automation. Patchright patches Chromium's automation detection signals to bypass Cloudflare and other bot-detection systems.
*   **🖥️ Headless Mode:** Run the bot in headless mode if you want to use the bot in server environment or while working with your computer. This allows the bot to operate without a visible browser window while maintaining full functionality.
*   **⏸️ Pause/Resume Control:** Pause the bot at any time by pressing `Ctrl+X` and continue when ready, giving you full control over execution without stopping the entire process.
*   **📊 Skill Statistics:** Analyzes job descriptions to identify the most in-demand skills, helping you tailor your resume effectively.
*   **🧠 Intelligent Error Handling:** If LinkedIn's Easy Apply feature encounters errors (e.g., incorrectly filled fields), the bot will attempt to fix them automatically.
*   **📈 Local Monitoring Dashboard:** Includes a local web dashboard for live monitoring, run history, screenshot review, config editing, bot controls, and JSON export of individual runs.
*   **💬 LinkedIn Messages Manager:** Includes a separate inbox triage workflow for classifying LinkedIn conversations, drafting replies, archiving spam, starring recruiter outreach, applying the `Jobs` label, and recording all message decisions to a persistent ledger for dashboard review.
*   **🤝 Automated Networking:** Includes a powerful tool to search for and connect with "Open Networkers" (LIONs) automatically, expanding your professional network with people likely to accept your requests.
*   **☑️ Smart Checkbox Handling:** Automatically detects and answers checkbox questions in LinkedIn Easy Apply forms with intelligent context-aware responses.
*   **🔗 Contextual Question Processing:** Considers previous answers when responding to follow-up questions like "If yes/no, who/when/where?" for more accurate and relevant responses.
*   **🤖 AI-Powered Resume Parsing:** Automatically parses your resume from a text file into a structured format using an LLM (Large Language Model).
*   **📄 Auto Resume Text Generation:** If `data/resumes/resume_text.txt` is missing but a PDF resume is present in `data/resumes/`, the bot automatically extracts the text from the PDF and generates a properly formatted `resume_text.txt` using the LLM — no manual transcription needed.
*   **📄 New Resume Style:** Includes the modern "FAANGPath" resume style for generating professional-looking resumes.
*   **📲 Telegram Integration:** Delivers comprehensive reports and error notifications directly to your Telegram chat after each run.
*   **💡 Resume Recommendations:** Provides AI-generated suggestions to improve your resume based on job market trends.
*   **🌐 Proxy Support:** Supports using proxies for both Gemini, OpenAI and OpenRouter models.
*   **🏗️ Robust Configuration:** Uses Pydantic models for validating configuration, resume, and other data structures, reducing runtime errors.
*   **🚀 Improved LLM Logic:**
    *   Utilizes improved system instructions and prompts for higher-quality LLM responses.
    *   Employs Gemini or OpenRouter as the default LLM, which is often more cost-effective (sometimes even free!) than OpenAI.
    *   Enhances question-answering logic to avoid LLM "hallucinations" by skipping questions where it lacks sufficient information.
*   **🔐 Secure Secrets Management:** Stores sensitive keys and credentials in a `.env` file for better security.
*   **🕒 Automated Scheduling:** A built-in timer allows the bot to run automatically every 24 hours.
*   **💻 Numerous improvements that simplify development and debugging:** advanced logging, pre-commit hooks, fast and easy installation using uv, etc.


## 🚀 Getting Started

### Prerequisites

*   Python 3.12
*   Git
*   [uv](https://github.com/astral-sh/uv) (optional, for faster installation)

### Installation

#### Option 1: Local Installation

1.  **Clone repository and create virtual environment**

    ```bash
    # Clone the repository
    git clone https://github.com/beatwad/LinkedIn-AI-Job-Applier-Ultimate.git
    cd LinkedIn-AI-Job-Applier-Ultimate
    ```

2.  **Install dependencies**
    ```bash
    uv sync
    ```

3.  **Install additional software**
    ```bash
    # Install Chromium browser for Playwright
    playwright install chromium
    ```

#### Option 2: Docker Installation

1.  **Clone repository**

    ```bash
    git clone https://github.com/beatwad/LinkedIn-AI-Job-Applier-Ultimate.git
    cd LinkedIn-AI-Job-Applier-Ultimate
    ```

2.  **Build Docker image**

    ```bash
    docker build -t linkedin .
    ```

3.  **Run Docker container**

    ```bash
    docker run -v $(pwd)/data:/app/data \
               -v $(pwd)/browser_session:/app/browser_session \
               -v $(pwd)/logs:/app/logs \
               linkedin
    ```

    **⚠️ IMPORTANT:** When running from Docker:
    - You **MUST** set `HEADLESS_MODE = True` in `config/app_config.py`. Docker containers don't support graphical interfaces, so the browser must run in headless mode.
    - The **Ctrl+X pause/resume feature will not work** in Docker (keyboard control requires an X server). The bot will run continuously without the ability to pause.
    - **Resume style selection is automatic** - the bot will use the default style (FAANGPath) instead of prompting for selection, since Docker doesn't support interactive prompts.

## 🔧 Configuration

1.  **Secrets (`.env` file):**
    Create a `.env` file in the root directory by copying the example file:
    ```bash
    cp .env_example .env
    ```
    Now, fill in the required values in your `.env` file:
    ```env
    # Your LinkedIn credentials (used when JOB_SITE="linkedin" in app_config.py)
    linkedin_email="your_linkedin_email@example.com"
    linkedin_password="your_linkedin_password"

    # Your Indeed credentials (used when JOB_SITE="indeed" in app_config.py)
    indeed_email="your_indeed_email@example.com"

    # Your LLM API Key (e.g., Gemini)
    llm_api_key="your_llm_api_key"

    # Optional proxy for LLM requests
    llm_proxy="http://your_proxy_url:port"

    # LLM endpoint URL (required for "openai_compatible", optional for "ollama")
    llm_api_url="http://localhost:8000/v1"

    # Your Telegram Bot Token for sending error messages and reports
    tg_token="your_telegram_bot_token"

    # Address of your chat in format "@name_of_your_chat"
    tg_chat_id="@name_of_your_chat"

    # ID of topic where bot will send error messages
    # You can find out ID of the topic by copying the link to the topic in Telegram app and extracting the number before the last slash
    # For example, if the link to the topic is https://t.me/channel_name/123/321, the ID of the topic is 123
    tg_err_topic_id="[ID of error topic]"

    # ID of topic where bot will send everyday report on the job applies done
    tg_report_topic_id="[ID of report topic]"
    ```

    Telegram options are optional. You can remove them from .env file and application will still be able to work but won't be able to set reports and error messages via Telegram.

2.  **Job Search Parameters (`config/search_config.yaml`):**
    Copy this file from `examples/config/search_config.yaml` and customize your job search by editing this file.
    You can define job titles, locations, experience levels and more.
    Example of search_config file can be found in `examples/config/search_config.yaml`

    ```yaml
    # Example: search for Mid-Senior level remote software engineer roles
    positions: # the only mandatory setting in search_config file
      - Software engineer

    remote: true
    hybrid: false
    onsite: false

    experience_level:
      mid_senior_level: true
    ```

3.  **Application Settings (`config/app_config.py`):**
    Copy this file from `examples/config/app_config.py` and fine-tune the bot's behavior in this file.
    Key settings include:
    *   `JOB_SITE`: The job platform to use. Set to `"linkedin"` (default) or `"indeed"`. Make sure to provide the matching credentials in your `.env` file.
    *   `MAX_APPLIES_NUM`: The maximum number of jobs to apply for in a single run.
    *   `HEADLESS_MODE`: If this mode is activated - the browser will be launched in headless mode. Convenient if you plan to
    use your computer while bot is working + everything works faster.
    *   `MONKEY_MODE`: If `True`, applies to all jobs found. If `False`, the LLM selects only the most suitable jobs.
    *   `TEST_MODE`: If `True`, the bot generates resumes and cover letters but does not actually submit applications.
    *   `COLLECT_INFO_MODE`: If `True`, the bot doesn't apply to the jobs or create resumes and cover letters, only gathers information for interesting jobs and their skill statistics and saves them to the files data/output/interesting_jobs.yaml and data/output/skill_stat.yaml.
    *   `UPLOAD_RESUME`: *(Indeed only)* If `False`, the bot selects your Indeed on-site resume instead of uploading a file. If `True`, the bot uploads a resume file (ready-made PDF or auto-generated).
    *   `INDEED_DOMAIN`: *(Indeed only)* The Indeed country domain to search on. Defaults to `"www.indeed.com"` (US) — set it to your own country's domain (e.g. `"ch.indeed.com"`, `"de.indeed.com"`, `"uk.indeed.com"`) or the search will return US jobs.
    *   `INDEED_SEARCH_RADIUS`: *(Indeed only)* Search radius around each configured location, in the units the chosen domain uses (miles on `www.indeed.com`, kilometres on most others). Leave as `None` to keep Indeed's default radius.
    *   `EASY_APPLY_ONLY_MODE`: *(LinkedIn only)* If `True`, bot applies only the jobs with Easy Apply. Else bot will apply to the jobs with Easy Apply and try to apply to the jobs with 3rd party applications. **WARNING**: applying to the jobs with 3rd-party applications is not guaranteed to be successful, but is guaranteed to consume at least 10-100x more tokens!
    *   `RESTART_EVERY_DAY`: *(LinkedIn only)* If `True`, bot will automatically restart the search every 24 hours when LinkedIn resets the search limits. So you don't have to restart it manually - just run & forget.
    *   `JOB_IS_INTERESTING_THRESH`: LLM evaluated the 'interest' level of the job from 1 to 100. If job 'interest' level not below this threshold - the job is considered interesting for bot. Otherwise not. Because of LinkedIn limits number of daily applications to 50, recommended value of this setting is 70+, so the bot will apply only to vacancies that match your resume
    *   `MINIMUM_WAIT_TIME_SEC`: Minimum time spent on one job application, this setting help to prevent ban for too frequent job applies
    *   `FREE_TIER`: If `True`, the bot will try to decrease RPM (requests per minute) to avoid rate limit errors when using free tier LLM services.
    *   `FREE_TIER_RPM_LIMIT`: desired RPM limit, application will try not to exceed this limit
    *   `DASHBOARD_OUTPUT_APP_LOGS`: If `True`, bot process log output is printed to the dashboard console (in addition to the log file `logs/dashboard_bot_stdout.log`). Useful for debugging when running the bot from the dashboard.
    *   `LLM_MODEL_TYPE`: Choose your LLM provider (e.g., "gemini").
    *   `EASY_APPLY_MODEL`: Specify the exact model to use for Easy Apply vacancies (e.g., "gemini-2.0-flash").
    *   `APPLY_AGENT_MODEL`: *(LinkedIn only)* Specify the exact agent model to use for Non-Easy Apply vacancies (e.g., "gemini-2.5-flash").
    *   `READY_MADE_RESUME_PATH`: Path to a ready-made resume PDF (e.g. `"data/resumes/resume.pdf"`). If set, the bot uses this file for every application instead of generating a new resume. If empty, a tailored resume is generated for each vacancy.
    *   `RESUME_STYLE`: Resume style to use for generated resumes. If set, skips the interactive style selection prompt. If `None`, prompts interactively (or falls back to default in Docker/headless mode). Possible values: `"FAANGPath"`, `"Cloyola Grey"`, `"Modern Blue"`, `"Modern Grey"`, `"Default"`, `"Clean Blue"`.

    **Supported LLM models**

    The bot supports multiple LLM providers. Configure them in `config/app_config.py` using `LLM_MODEL_TYPE` and `EASY_APPLY_MODEL`.

    **Gemini (Google)**
    - Set: `LLM_MODEL_TYPE = "gemini"`
    - Examples: `gemini-3.1-flash-lite`, `gemini-3.1-flash`

    **OpenAI**
    - Set: `LLM_MODEL_TYPE = "openai"`
    - Examples: `gpt-4o`, `gpt-4o-mini`

    **OpenRouter**
    - Set: `LLM_MODEL_TYPE = "openrouter"`
    - Examples: `google/gemini-3.1-flash-lite`, `google/gemini-3.1-flash`, `openai/gpt-4o-mini`

    **Claude (Anthropic)**
    - Set: `LLM_MODEL_TYPE = "claude"`
    - Examples: `claude-3-5-sonnet`, `claude-4-opus` (use any valid Claude model ID)

    **Ollama (local/server)**
    - Set: `LLM_MODEL_TYPE = "ollama"`
    - Examples: `llama3`, `qwen2.5` (any model available in your Ollama)

    **OpenAI-compatible endpoint (vLLM, LM Studio, llama.cpp server, etc.)**
    - Set: `LLM_MODEL_TYPE = "openai_compatible"`
    - Set the endpoint URL in `.env` as `llm_api_url` (e.g. `http://localhost:8000/v1`)
    - Examples: any model name served by your endpoint; if the endpoint doesn't require an API key, `llm_api_key` can be set to any placeholder value

    Notes:
    - Recommended models: gemini + gemini-3.1-flash-lite or openai + gpt-5-mini - both are fast, clever and cheap (gemini models can be even free!)
    - Provide your API key in `.env` as `llm_api_key`. Optionally set `llm_proxy`.
    - Model pricing used in reports is taken from an internal map for common models; others fall back to default per-token prices.

4.  **Connection Searcher Settings (`config/linkedin_connection_searcher_config.yaml`):**
    Copy this file from `examples/config/linkedin_connection_searcher_config.yaml` and fine tune the automated networking tool behaviour in this file.
    *   `main_search_words`: Keywords like "Open Networker" or "LION" used to find networking-oriented profiles.
    *   `additional_search_words`: Keywords to narrow down the search to your specific field (e.g., "ai", "ml", "data science").
    The bot will search for every combination of these words and attempt to connect with users whose profiles indicate they are open networkers (while intelligently skipping those profiles where the keywords appear only in "mutual connections").

5.  **LinkedIn Messages Manager Settings (`config/linkedin_messages_manager_config.yaml`):**
    This is a separate configuration file for the LinkedIn inbox triage workflow launched by `uv run python linkedin_messages.py`.

    It controls things like:
    *   dry run versus execute mode
    *   whether archives are allowed
    *   whether replies are allowed
    *   unread-only scanning
    *   whether recruiter messages are auto-starred
    *   whether recruiter messages are auto-labeled as `Jobs`
    *   reply tone and formatting rules
    *   how old-message apology context should work

    Because this feature is more nuanced than the main job application flow, it has dedicated documentation:

    `docs/linkedin-messages-manager.md`

6.  **Resume files for LLM (`data/resumes/resume_text.txt` and `data/resumes/structured_resume.yaml`):**
    Resume text must contain information about your first and last names and your gender (that is necessary for the correct work of anonymization functions).
    Bot needs to resume files for correct work:
    *   **raw resume text file** (`resume_text.txt`) which contains all available information about your resume in text format and is used to answer the questions and write cover letters (I find out that using full resume text for these tasks is more reliable + saves input token + you don't need to determine which resume section you have to use). **TIP**: Try to add to this file as much information about youself as possible - that will let bot to answer questions more precisely and better tailor your resume to a specific vacancy.
    *   **structured resume file** (`structured_resume.yaml`) which is used for tailored resume generation

    You have two options for providing the resume text file:
    *   **Automatic Generation from PDF (recommended for new users):** If `resume_text.txt` is missing but a PDF resume exists in `data/resumes/`, the bot will automatically extract the text from the PDF using an LLM and save it as `data/resumes/resume_text.txt` before the run starts. Just drop your resume PDF into `data/resumes/` and run the bot — no manual text editing required. Review the generated file afterwards and add any missing details (salary expectations, preferences, etc.) to improve answer quality.
    *   **Manual creation:** Copy `examples/data/resumes/resume_text.txt` to `data/resumes/resume_text.txt` and fill it in by hand. **TIP:** The more detail you add, the more precisely the bot can answer application questions and tailor your resume.

    With structured resume file you have two options:
    *   **Automatic Parsing (recommended):** The bot will use the LLM to parse your resume text file into a structured format on the first run and save it in `data/resumes/structured_resume.yaml`. Just add raw resume text to your project and run the bot - it will do the rest. Also if you want to update your resume info - add it to `resume_text.txt`, delete `structured_resume.yaml` and run the bot again - it will create updated `structured_resume.yaml` file. Another way of auto creating structured resume is to run `uv run python src/resume_builder/resume_manager.py` command - it will create `structured_resume.yaml` file if it doesn't exist.
    *   **Manual Structure:** fill out file `structured_resume.yaml` manually for precise control. Why use this option instead of first? Because if you select the first option, all data from your resume text will be sent to the LLM to create the structured_resume file — for some people who care about their privacy this would be unacceptable. I want to point out that Automatic Parsing and Non-Easy Apply vacancies applying are the only two functions of this bot that send not anonymized user's personal information to LLM. All other bot functions anonymize personal information before sending it to LLM.
    Examples of `resume_text.txt` and `structured_resume.yaml` files can be found in `examples/data/resumes` folder

7. **On-site profile/resume (LinkedIn and Indeed):**
    Before running the bot, make sure your profile on the job site is as complete as possible:
    *   **LinkedIn:** Go to your LinkedIn profile and fill in all sections — work experience, education, skills, certifications, contact info, etc. Also upload your resume in the **Easy Apply settings** (LinkedIn → Job Preferences → Easy Apply Resume). LinkedIn pre-fills application forms from your profile and saved resume, so the more complete they are, the fewer questions the bot needs to answer via LLM — saving you tokens and money.
    *   **Indeed:** Go to your Indeed profile and fill in all sections — work history, education, skills, licenses, desired salary, etc. Indeed uses your on-site profile to auto-fill Easy Apply forms, so a thorough profile means fewer questions the bot has to send to the LLM.

8. **Resume generation:**
    You have two options:
    *   **Automatic Creation (recommended):** Leave `READY_MADE_RESUME_PATH` empty in `config/app_config.py` and the bot will generate a new resume tailored to each vacancy. Generated resumes are stored in `data/resumes/generated_resumes/`. Sections that are the same across vacancies (e.g. header) are generated once and cached in `data/resumes/templates/<section_name>.html`. Delete a cached file to force re-generation.
    *   **Ready-Made Resume:** Set `READY_MADE_RESUME_PATH` in `config/app_config.py` to the path of your resume PDF (e.g. `"data/resumes/resume.pdf"`). The bot will use that file for every application.

    **I also recommend to test resume generation before starting applying jobs**.

    ### How to test resume generation using bot
    1.  Fill file `data/resumes/resume_text.txt` with information from your resume. Example of resume_text.txt file can be found in `examples` folder. You can also fill `structured_resume.yaml` manually, but if you don't want to do it - just move to step 2.
    2.  Run this command

        ```bash
        uv run python src/resume_builder/resume_manager.py
        ```
        If you don't have `structured_resume.yaml` file - bot will create it automatically using `resume_text.txt` file during this step.
    3.  Select resume style (first style FAANGPath is recommended).
    4.  Output file is `test_generated_resume.pdf` in root directory
    5.  Carefully read the resume, look for **No info**, **N/A** or **None** text in it. If you find it - that means that some critical information in your resume text is missing and you must add it to your resume file(s) and repeat the resume creation process.
    6.  If you are satisfied with the quality of your resume - move the output file to any path you like (e.g. `data/resumes/resume.pdf`) and set `READY_MADE_RESUME_PATH` in `config/app_config.py` to that path. The bot will use it for every application.

## ▶️ Usage

Once you have completed the installation and configuration steps, you can run the bot:

```bash
uv run python main.py
```

If bot finds out that there are no information about some fields in your `structured_resume.yaml` file - it will output warning, list of fields with no information and propose two options:
- press `y` to continue anyway
- press `n` to finish bot execution, consider what information is missing and add it to `data/resumes/resume_text.txt`. Then delete `structured_resume.yaml` and restart bot OR fill missing fields in `structured_resume.yaml` manually if you don't want LLM to re-generate it automatically because of privacy issues.

If 30 seconds pass or you select `y` or all fields in the `structured_resume.yaml` file are filled, the bot will continue work.

The bot will log its progress in the console and create detailed log files in the `logs/` directory. Upon completion, it will send a report to your configured Telegram chat.

**Pause/Resume:** While the bot is running, and you see that it behaves incorrectly - you can pause it by pressing `Ctrl+X`. Press `Ctrl+X` again to resume. This is useful if you need to temporarily stop the bot without terminating the entire process. **Bot won't stop immediately**, usually couple of seconds may pass after you press Ctrl + X.

### LinkedIn Messages Manager

The repository also includes a separate LinkedIn inbox triage workflow.

Run it with:

```bash
uv run python linkedin_messages.py
```

This workflow is designed for LinkedIn messages, not job applications. It can:

- scan your inbox
- optionally filter to unread conversations only
- classify conversations with the LLM
- skip threads where you already replied
- draft replies for important conversations
- archive spam or low-value threads
- star recruiter outreach
- label recruiter conversations as `Jobs`
- write every processed result to `data/output/linkedin/messages_dry_run.yaml`
- display results on the dashboard messages page

This feature has several safety rules and configuration options, so it is documented separately here:

`docs/linkedin-messages-manager.md`

### Dashboard

The project now includes a local monitoring dashboard for observing the bot in real time and inspecting past runs.

Start the dashboard with:

```bash
uv run python dashboard.py
```

Open it in your browser at:

```text
http://127.0.0.1:8000
```

The dashboard supports:

- starting a bot run from the browser
- pause, resume, and graceful stop controls
- live counters for discovered, evaluated, interesting, applied, skipped, and failed jobs
- current-job stage tracking during Easy Apply flows
- live event timeline powered by server-sent events
- historical run list with deep links like `/runs/<run_id>`
- per-run jobs, screenshots, and event history
- search config editing for `config/search_config.yaml`
- selected app config editing for `config/app_config.py`
- exporting a full run as JSON

### Dashboard Routes And APIs

Main pages:

- `/` - live dashboard
- `/runs/<run_id>` - deep-linked dashboard focused on a specific run

Useful API routes:

- `/api/summary` - top-level dashboard counters and current run state
- `/api/live` - current live snapshot and recent events
- `/api/jobs` - global jobs board from persisted output files plus current in-progress job
- `/api/runs` - run history built from structured dashboard events
- `/api/runs/<run_id>` - full run detail payload
- `/api/runs/<run_id>/jobs` - jobs reconstructed for a specific run
- `/api/runs/<run_id>/events` - events for a specific run
- `/api/runs/<run_id>/screenshots` - screenshot history for a specific run
- `/api/runs/<run_id>/export` - downloadable JSON export for a specific run
- `/api/control/start` - start the bot in the background
- `/api/control/pause` - request pause
- `/api/control/resume` - request resume
- `/api/control/stop` - request graceful stop

Dashboard data is stored under `data/output/dashboard/` and includes:

- `events.jsonl` - structured runtime events used for live monitoring and run reconstruction
- `snapshot.json` - latest live snapshot for the active or most recent run
- `control.json` - pause/stop requests written by the dashboard
- `process.json` - background process metadata
- `screenshots.json` - metadata index for archived screenshots
- `screenshots/` - latest screenshot and per-run screenshot history

If you want a more detailed dashboard guide, see `docs/dashboard.md`.

### Output files (`data/output/`)

- **answers.yaml**: Stores previously given answers to LinkedIn application questions to reuse across runs and reduce LLM calls.
- **failed.yaml**: Companies and jobs where an application attempt failed due to an error, with reasons.
- **interesting_jobs.yaml**: Jobs flagged as interesting by the LLM along with interest score, reasoning, and extracted key skills, sorted by descending interesting score.
- **last_run.yaml**: Internal cache with timestamps and counters (e.g., `last_run`, `last_apply`, totals) used to enforce the 24-hour scheduling logic.
- **resume_recommendations.txt**: AI-generated recommendations for improving your resume, produced once and reused unless deleted.
- **skill_stat.yaml**: Aggregated statistics of the most frequently requested skills gathered from job descriptions, sorted by descending frequency.
- **skipped.yaml**: Companies and jobs that were intentionally skipped (e.g., blacklist, missing info, not interesting), with reasons.
- **success.yaml**: Companies and jobs where the bot successfully submitted an application, including basic job info.


### Automated Networking (Connection Searcher)

To run the networking tool that finds and connects with Open Networkers:

```bash
uv run python linkedin_connection_searcher.py
```

This tool will use the settings in `config/linkedin_connection_searcher_config.yaml` to search for potential connections on LinkedIn and send invitations automatically.

Bot uses main keywords like "Open Networker" or "LION" to find people who are open for networking. You can also set your own additional keywords in `config/linkedin_connection_searcher_config.yaml` file to search for specific people (e.g. if you are ML Engineer - you can add "ml" or "data science" keywords to search for another ML Engineers). The bot will search for every combination of main and additional keywords and attempt to connect with users whose profiles indicate they are open networkers (while intelligently skipping those profiles where the keywords only appear in "mutual connections").

## 💵 Vacancy application cost

### Easy Apply

What operations the LLM performs to apply to a vacancy:
- determine if vacancy is interesting for applying or not
- extract key skills that are necessary for this vacancy
- create resume for this vacancy (if necessary)
- write cover letter (if necessary)
- answer questions (from 1-2 to 20+ per vacancy)

Total token usage:
- **input tokens**: 5000-15000
- **output tokens**: 100-5000

For default model (gemini-2.0-flash) the cost will be `$0.0005 - $0.0035`, not so much money, huh?

And this is calculation for the paid plan. If you're on the free plan - you will pay nothing 😉, but may face some quota errors (look [🐞 Troubleshooting](#-troubleshooting) paragraph below)

### Non-Easy Apply

What operations the LLM performs to apply to a vacancy:
- scan HTML page or take screenshot and send these data to LLM
- make necessary actions to apply vacancy using browser (click, scroll, type, select, etc.)

This is agentic flow and it consumes **A LOT** of tokens. You can multiply previous cost values like 10x-100x times!

So we do not recommend you to use this mode until you have enough money for that and understand what you are doing.

**Note:** If the AI agent encounters a registration form on a 3rd-party application site, it will use your `linkedin_email` as the login and `<linkedin_email_part_before_@>_123456` as the password (e.g. if your email is `john.doe@gmail.com`, the password will be `john.doe_123456`).

## ✅ Running Tests

The project includes a suite of tests to ensure its functionality. To run them, first install the development dependencies:

```bash
uv sync --dev
```

Then, run pytest from the root directory:

```bash
pytest
```

## 🐞 Troubleshooting

### 1. LLM API errors

**Issue:** Bot throws errors like:
```bash
google.api_core.exceptions.ResourceExhausted: 429 You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits.
```

**Solution:**

- increase MINIMUM_WAIT_TIME_SEC in `config/app_config.py` to 15-30 sec
- move from free plan to paid

### 2. Incorrect Information in Job Applications

**Issue:** Bot provides inaccurate data for experience, salary, and notice period

**Solution:**

- Update prompts for professional experience specificity (can be found in `src/llm/prompts.py`)
- Add fields in `structured_resume.yaml` for experience, expected salary, and notice period

### 3. YAML Configuration Errors

**Error Message:**

yaml.scanner.ScannerError: while scanning a simple key

**structured_resume.yaml**

If error happens when `structured_resume.yaml` is processed - delete it and restart the bot - it will parse resume_text.txt file and generates new correct `structured_resume.yaml` file.

**search_config.yaml**
If error happens when `search_config.yaml` is processed:
- Copy example of `search_config.yaml` from `examples/config/` to `config/` and modify gradually
- Ensure proper YAML indentation and spacing
- Use a YAML validator tool
- Avoid unnecessary special characters or quotes

### 4. Bot Logs In But Doesn't Apply to Jobs

**Issue:** Bot doesn't start at all or starts without applying

**Solution:**

- Delete file `data/output/last_run.yaml` if it exists. It is used for scheduling of bot run every 24 hours, but if previous run was less than 24 hours ago - bot would just stop applying
- Check for security checks or CAPTCHAs
- Verify `search_config.yaml` parameters
- Check how many vacancies can be found on LinkedIn with search settings like in your `search_config.yaml` file (maybe LinkedIn can't find any)
- Ensure your account profile meets job requirements
- Review console output for error messages

### General Troubleshooting Tips

- Use the latest version of the bot
- Verify all dependencies are installed and updated
- Check internet connection stability
- Clear browser cache and cookies if issues persist (by deleting all files in the `browser_session` folder in the root directory)
- In some cases users with Premium LinkedIn subscription have different LinkedIn user interface, which may lead to errors in bot's work, e.g. bot can't parse information about job. If you face similar errors - try to use bot with user account without Premium.

## 📨 Telegram Instruction

1. Create Telegram bot and obtain your token following [this](https://core.telegram.org/bots/tutorial#obtain-your-bot-token) guide for example. Set tg_token variable with your new obtained token in .env file.

2. Create group with topics following [this](https://docs.hetrixtools.com/how-to-enable-telegram-topics/) guide for example

3. Make group public (Tap on group name -> Edit -> Group Type -> Public)

4. Set group's permanent link, e.g. t.me/linkedin_bot_feedback.

5. Set TG_CHAT_ID in `config/app_config.py` with this link, e.g. TG_CHAT_ID = "@linkedin_bot_feedback"

6. Create two topics: one for errors and another for reports

7. Send a message to every topic in the chat. Then click on that message and select *Copy Message Link*. You will get a link like: https://t.me/c/194xxxx987/11/13, so the group Topic ID is 11. Set TG_ERR_TOPIC_ID in `config/app_config.py` with Error Topic ID and TG_REPORT_TOPIC_ID - with Report Topic ID.

## 🤝 Contributing

Contributions are welcome! If you have suggestions for improvements or find a bug, please feel free to open an issue. If you want to submit a pull request, please read the rules below.

### Pull Request Rules

1. One PR is one major feature or bug fix. If changes are small - you can combine them in one PR, but please don't put multiple major features/bug fixes in one PR: some of that features can be acceptable, some are not, but they are in one PR so they can be accepted or rejected only together, which is not good.

2. Run `uv run pytest` and make sure all tests pass. If some tests fail - fix them or fix code or provide the reason why failed tests should be skipped. PRs that break existing tests will be rejected.

3. Test your changes in real environment and make sure they don't break existing functionality. PRs that break existing functionality will be rejected.

4. Don't forget to add description of what you've changed and why.

## 📜 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgements

*   This project is a fork of and builds upon the excellent work of the original [Jobs_Applier_AI_Agent_AIHawk](https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk) project.
*   Non-Easy Apply vacancies are applied using [browser-use](https://github.com/browser-use/browser-use) project.
*   System instructions for the LLM were adapted from this [GitHub repository](https://github.com/DenisSergeevitch/chatgpt-custom-instructions/blob/main/v2.md).
*   The FAANGPath resume style is based on this [Overleaf template](https://www.overleaf.com/latex/templates/faangpath-simple-template/npsfpdqnxmbc).

If you like the project please star ⭐ the repository!
