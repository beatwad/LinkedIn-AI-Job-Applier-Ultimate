## Configuration


### Runtime Flags (`config/app_config.py`)
- `JOB_SITE` — target platform: `"linkedin"` (default) or `"indeed"`
- `MAX_APPLIES_NUM` — max applications per run
- `HEADLESS_MODE` — headless browser (required for Docker)
- `MONKEY_MODE` — skip LLM job filtering, apply to all
- `TEST_MODE` — generate resumes/cover letters without submitting
- `COLLECT_INFO_MODE` — gather stats only, no applications
- `UPLOAD_RESUME` — (Indeed only) upload a resume file if `True`; use Indeed on-site resume if `False`
- `INDEED_DOMAIN` — (Indeed only) country domain to search on, e.g. `"www.indeed.com"` (US, default), `"ch.indeed.com"`, `"de.indeed.com"`, `"uk.indeed.com"`
- `INDEED_SEARCH_RADIUS` — (Indeed only) search radius around each location in the domain's units; `None` keeps Indeed's default
- `EASY_APPLY_ONLY_MODE` — skip non-Easy Apply jobs (LinkedIn only; Indeed always uses Easy Apply flow)
- `RESTART_EVERY_DAY` — auto-restart every 24h (LinkedIn only)
- `READY_MADE_RESUME_PATH` — path to a ready-made resume PDF; if empty, a new resume is generated per vacancy
- `RESUME_STYLE` — style for generated resumes (`"FAANGPath"`, `"Cloyola Grey"`, `"Modern Blue"`, `"Modern Grey"`, `"Default"`, `"Clean Blue"`); `None` prompts interactively
- `LLM_MODEL_TYPE` — provider: `"gemini"`, `"openai"`, `"openrouter"`, `"claude"`, `"ollama"`
- `EASY_APPLY_MODEL` — model name for Easy Apply
- `APPLY_AGENT_MODEL` — model name for Non-Easy Apply agent (LinkedIn only)
- `JOB_IS_INTERESTING_THRESH` — LLM interest score threshold (1-100)
- `MINIMUM_WAIT_TIME_SEC` — minimum seconds per application (rate limiting)
- `TEMPERATURE` — LLM temperature (higher = more creative, lower = more deterministic)
- `FREE_TIER` / `FREE_TIER_RPM_LIMIT` — RPM throttling for free-tier LLMs
- `DEBUG_MODE` — saves screenshots + page HTML to `data/debug/` on every selector failure; also enables Playwright tracing (saved to `data/debug/trace.zip` on exit, viewable at `trace.playwright.dev`)
