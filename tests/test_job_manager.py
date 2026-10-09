from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from src.job_manager.linkedin.job_manager_linkedin import LinkedInJobManager
from src.pydantic_models.job_models import Job, JobManagerCache

# yaml is intentionally not imported to avoid real file I/O in tests


@pytest.fixture
def mock_page():
    """Create a mock Playwright page object"""
    page = MagicMock()
    page.url = "https://linkedin.com/jobs/view/12345"
    return page


@pytest.fixture
def mock_resume_anonymizer():
    """Create a mock resume anonymizer"""
    anonymizer = MagicMock()
    anonymizer.deanonymize_text = lambda text: text
    return anonymizer


@pytest.fixture
def mock_search_component():
    """Create a mock search component"""
    return MagicMock()


@pytest.fixture
def mock_file_system():
    """Mock all file system operations to prevent actual file I/O"""
    with (
        patch("builtins.open", mock_open()) as mock_file,
        patch("yaml.safe_load") as mock_yaml_load,
        patch("yaml.dump") as mock_yaml_dump,
        patch("pathlib.Path.exists") as mock_exists,
        patch("pathlib.Path.mkdir") as mock_mkdir,
    ):
        mock_yaml_load.return_value = {}
        mock_yaml_dump.return_value = ""
        mock_exists.return_value = False

        yield {
            "open": mock_file,
            "yaml_load": mock_yaml_load,
            "yaml_dump": mock_yaml_dump,
            "exists": mock_exists,
            "mkdir": mock_mkdir,
        }


@pytest.fixture
def job_applier(mock_page, mock_resume_anonymizer, mock_search_component):
    """Create a LinkedInJobManager instance for testing with mocked file operations"""
    with (
        patch("src.job_manager.job_manager.OUTPUT_DIR", "/mock/output"),
        patch(
            "src.job_manager.job_manager.LAST_RUN_FILE",
            Path("/mock/output/last_run.yaml"),
        ),
        patch("builtins.open", mock_open()),
        patch("yaml.safe_load", return_value={}),
        patch("yaml.dump", return_value=""),
    ):
        applier = LinkedInJobManager(
            page=mock_page,
            linkedin_email="test@example.com",
            resume_anonymizer=mock_resume_anonymizer,
            search_component=mock_search_component,
        )
        return applier


class TestJobApplierInitialization:
    """Test LinkedInJobManager initialization"""

    def test_init_sets_basic_attributes(
        self, mock_page, mock_resume_anonymizer, mock_search_component
    ):
        """Test that __init__ sets all basic attributes correctly"""
        applier = LinkedInJobManager(
            page=mock_page,
            linkedin_email="test@example.com",
            resume_anonymizer=mock_resume_anonymizer,
            search_component=mock_search_component,
        )

        assert applier.page == mock_page
        assert applier.email == "test@example.com"
        assert applier.resume_anonymizer == mock_resume_anonymizer
        assert applier.search_component == mock_search_component
        assert applier.llm_answerer_component is None
        assert applier.llm_agent_component is None
        assert applier.resume_generator_manager is None
        assert applier.jobs_no_info == []
        assert applier.job_key_skills == []
        assert applier.interesting_jobs == []
        assert applier.page_num == 0
        assert applier.resume_vac_page_num == -1
        assert applier.error_num == 0
        assert applier.total_applies_num == 0
        assert applier.resume_recommendations == ""


class TestSetters:
    """Test setter methods"""

    def test_set_answerer_and_agent(self, job_applier):
        """Test setting LLM answerer and agent components"""
        mock_answerer = MagicMock()
        mock_agent = MagicMock()

        job_applier.set_answerer_and_agent(mock_answerer, mock_agent)

        assert job_applier.llm_answerer_component == mock_answerer
        assert job_applier.llm_agent_component == mock_agent

    def test_set_resume(self, job_applier):
        """Test setting resume data"""
        resume_data = {
            "personal_information": {"name": "John Doe"},
            "experience": ["Software Engineer at Company A"],
        }

        job_applier.set_resume(resume_data)

        assert job_applier.resume == resume_data

    def test_set_resume_generator_manager(self, job_applier):
        """Test setting resume generator manager"""
        mock_generator = MagicMock()

        job_applier.set_resume_generator_manager(mock_generator)

        assert job_applier.resume_generator_manager == mock_generator


class TestSetParameters:
    """Test set_parameters method"""

    def test_set_parameters_basic_attributes(self, job_applier):
        """Test setting basic parameters"""
        # Mock the loading methods to avoid file I/O
        with (
            patch.object(job_applier, "_load_companies_from_yaml", return_value={}),
            patch.object(job_applier, "_load_data_from_yaml", return_value=[]),
            patch.object(job_applier, "_load_cache", return_value=JobManagerCache()),
        ):
            parameters = {
                "apply_once_at_company": True,
                "company_blacklist": ["BadCompany Inc", "Evil Corp"],
            }

            job_applier.set_parameters(parameters)

            assert job_applier.apply_once_at_company is True
            assert "badcompany inc" in job_applier.job_blacklist
            assert "evil corp" in job_applier.job_blacklist
            assert job_applier.applies_num == 0

    def test_set_parameters_treats_none_company_blacklist_as_empty(self, job_applier):
        with (
            patch.object(job_applier, "_load_companies_from_yaml", return_value={}),
            patch.object(job_applier, "_load_data_from_yaml", return_value=[]),
            patch.object(job_applier, "_load_cache", return_value=JobManagerCache()),
        ):
            job_applier.set_parameters({"company_blacklist": None})

        assert job_applier.job_blacklist == []


class TestCacheManagement:
    """Test cache loading and writing"""

    def test_load_cache_empty(self, job_applier):
        """Test loading cache when file doesn't exist"""
        with patch("builtins.open", side_effect=FileNotFoundError):
            cache = job_applier._load_cache()

            assert isinstance(cache, JobManagerCache)
            assert cache.last_run is None
            assert cache.last_apply is None
            assert cache.success_applies_num == 0
            assert cache.total_applies_num == 0

    def test_load_cache_with_data(self, job_applier):
        """Test loading cache with existing data"""
        cache_data = {
            "last_run": "2025-10-14T10:00:00",
            "last_apply": "2025-10-14T11:00:00",
            "success_applies_num": 5,
            "total_applies_num": 100,
        }

        with patch("builtins.open", mock_open()), patch("yaml.safe_load", return_value=cache_data):
            cache = job_applier._load_cache()

            assert cache.last_run == "2025-10-14T10:00:00"
            assert cache.last_apply == "2025-10-14T11:00:00"
            assert cache.success_applies_num == 5
            assert cache.total_applies_num == 100

    def test_write_the_last_search_time(self, job_applier):
        """Test writing cache to file"""
        job_applier.cache = JobManagerCache(
            last_run="2025-10-14T10:00:00",
            success_applies_num=10,
            total_applies_num=50,
        )

        mock_file = mock_open()
        with (
            patch("builtins.open", mock_file),
            patch("src.job_manager.job_manager.save_yaml_file") as mock_save,
        ):
            job_applier._write_the_last_search_time()

            mock_save.assert_called_once()
            call_args = mock_save.call_args[0]
            assert call_args[1]["last_run"] == "2025-10-14T10:00:00"
            assert call_args[1]["success_applies_num"] == 10
            assert call_args[1]["total_applies_num"] == 50


class TestTimeChecking:
    """Test time-related checking methods"""

    def test_check_the_last_search_time_no_previous_run(self, job_applier):
        """Test when there's no previous run"""
        job_applier.cache = JobManagerCache()

        result = job_applier.check_the_last_search_time()

        assert result is True

    def test_check_the_last_search_time_24_hours_passed(self, job_applier):
        """Test when 24 hours have passed since last run"""
        past_time = datetime.now() - timedelta(hours=25)
        job_applier.cache = JobManagerCache(last_run=past_time.isoformat())

        result = job_applier.check_the_last_search_time()

        assert result is True

    def test_check_the_last_search_time_too_soon(self, job_applier):
        """Test when less than 24 hours have passed"""
        recent_time = datetime.now() - timedelta(hours=12)
        job_applier.cache = JobManagerCache(last_run=recent_time.isoformat())
        job_applier.previous_apply_number = 0

        result = job_applier.check_the_last_search_time()

        assert result is False


class TestVacancyParsing:
    """Test LinkedIn vacancy parsing"""

    @pytest.mark.asyncio
    async def test_extract_job_url_from_relative_href(self, job_applier):
        """Test extracting a job URL from a relative link"""
        job_element = AsyncMock()
        job_element.get_attribute.return_value = None

        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.get_element_attribute_safely",
            new_callable=AsyncMock,
        ) as mock_get_attribute:
            mock_get_attribute.return_value = "/jobs/view/12345/"

            job_url = await job_applier._extract_job_url(job_element)

            assert job_url == "https://www.linkedin.com/jobs/view/12345/"

    @pytest.mark.asyncio
    async def test_extract_job_url_from_data_job_id(self, job_applier):
        """Test extracting a job URL from a job id attribute"""
        job_element = AsyncMock()

        async def get_attribute_side_effect(name):
            return "12345" if name == "data-occludable-job-id" else None

        job_element.get_attribute.side_effect = get_attribute_side_effect

        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.get_element_attribute_safely",
            new_callable=AsyncMock,
        ) as mock_get_attribute:
            mock_get_attribute.return_value = None

            job_url = await job_applier._extract_job_url(job_element)

            assert job_url == "https://www.linkedin.com/jobs/view/12345"
            mock_get_attribute.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_vacancies_from_page_skips_bad_selector_matches(self, job_applier):
        """Test vacancy parsing continues past selectors without job URLs"""
        first_selector_elements = [AsyncMock(), AsyncMock()]
        for element in first_selector_elements:
            element.get_attribute.return_value = None

        valid_element = AsyncMock()

        async def valid_get_attribute(name):
            if name == "href":
                return None
            if name == "data-occludable-job-id":
                return "67890"
            return None

        valid_element.get_attribute.side_effect = valid_get_attribute

        with (
            patch.object(job_applier, "_scroll_to_load_jobs", new_callable=AsyncMock),
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_elements_safely",
                new_callable=AsyncMock,
            ) as mock_find_elements,
        ):
            mock_find_elements.side_effect = [
                first_selector_elements,
                [valid_element],
            ]

            vacancies = await job_applier.get_vacancies_from_page()

            assert vacancies == [{"url": "https://www.linkedin.com/jobs/view/67890", "id": "67890"}]

    def test_check_previous_apply_number_no_previous(self, job_applier):
        """Test when there's no previous application"""
        job_applier.cache = JobManagerCache()

        result = job_applier._check_the_previous_apply_number()

        assert result == 0

    def test_check_previous_apply_number_recent_apply(self, job_applier):
        """Test when there's a recent application (< 59 minutes ago)"""
        recent_time = datetime.now() - timedelta(minutes=30)
        job_applier.cache = JobManagerCache(
            last_apply=recent_time.isoformat(), success_applies_num=5
        )

        result = job_applier._check_the_previous_apply_number()

        assert result == 5

    def test_check_previous_apply_number_old_apply(self, job_applier):
        """Test when last application was more than 59 minutes ago"""
        old_time = datetime.now() - timedelta(hours=2)
        job_applier.cache = JobManagerCache(last_apply=old_time.isoformat(), success_applies_num=5)

        result = job_applier._check_the_previous_apply_number()

        assert result == 0


class TestJobInfoCollection:
    """Test job info collection methods"""

    def test_collect_job_info(self, job_applier):
        """Test collecting job information"""
        job_applier._collect_job_info(
            company_job_title="Software Engineer",
            company_name="Tech Corp",
            job_link="https://linkedin.com/jobs/view/12345",
            reason="Missing information",
        )

        assert len(job_applier.jobs_no_info) == 1
        job_info = job_applier.jobs_no_info[0]
        assert job_info["job_title"] == "Software Engineer"
        assert job_info["company_name"] == "Tech Corp"
        assert job_info["url"] == "https://linkedin.com/jobs/view/12345"
        assert job_info["skip_reason"] == "Missing information"


class TestSkillStatistics:
    """Test skill statistics management"""

    def test_update_skill_stat_simple_skills(self, job_applier):
        """Test updating skill statistics with simple skills"""
        with patch.object(job_applier, "_save_data_to_yaml"):
            job_applier.skill_stat = {}

            skills = ["Python", "JavaScript", "Python"]
            job_applier._update_skill_stat(skills)

            assert job_applier.skill_stat["Python"] == 2
            assert job_applier.skill_stat["JavaScript"] == 1

    def test_update_skill_stat_with_semicolons(self, job_applier):
        """Test updating skill statistics with semicolon-separated skills"""
        with patch.object(job_applier, "_save_data_to_yaml"):
            job_applier.skill_stat = {}

            skills = ["Python; JavaScript", "Docker"]
            job_applier._update_skill_stat(skills)

            assert job_applier.skill_stat["Python"] == 1
            assert job_applier.skill_stat["JavaScript"] == 1
            assert job_applier.skill_stat["Docker"] == 1

    def test_process_skill_string(self, job_applier):
        """Test processing skill string with semicolons"""
        skill_string = "Python; JavaScript; Docker"

        result = job_applier._process_skill_string(skill_string)

        assert result == ["Python", "JavaScript", "Docker"]

    def test_process_skill_string_with_special_chars(self, job_applier):
        """Test processing skill string with special characters"""
        skill_string = "Python@3.9; Node.js!"

        result = job_applier._process_skill_string(skill_string)

        assert result == ["Python39", "Nodejs"]


class TestCompanyManagement:
    """Test company saving and loading"""

    def test_is_blacklisted(self, job_applier):
        """Test checking if company is blacklisted"""
        job_applier.job_blacklist = ["bad company", "evil corp"]

        assert job_applier._is_blacklisted("bad company") is True
        assert job_applier._is_blacklisted("good company") is False

    def test_save_company_success(self, job_applier):
        """Test saving company to success list"""
        with patch.object(job_applier, "_save_company_to_yaml"):
            job_applier.success_companies = {}
            job_applier.skipped_companies = {}
            job_applier.failed_companies = {}

            job = Job(
                job_title="Software Engineer",
                company_name="Tech Corp",
                url="https://linkedin.com/jobs/view/12345",
            )
            vacancy = {"url": "https://linkedin.com/jobs/view/12345"}
            apply_result = ("Success", "")

            job_applier._save_company(job, apply_result, vacancy)

            assert "Tech Corp" in job_applier.success_companies
            assert len(job_applier.success_companies["Tech Corp"]) == 1
            assert job_applier.success_companies["Tech Corp"][0]["job_title"] == "Software Engineer"

    def test_save_company_skip(self, job_applier):
        """Test saving company to skipped list"""
        with patch.object(job_applier, "_save_company_to_yaml"):
            job_applier.success_companies = {}
            job_applier.skipped_companies = {}
            job_applier.failed_companies = {}

            job = Job(
                job_title="Software Engineer",
                company_name="Tech Corp",
                url="https://linkedin.com/jobs/view/12345",
            )
            vacancy = {"url": "https://linkedin.com/jobs/view/12345"}
            apply_result = ("Skip", "Not interesting")

            job_applier._save_company(job, apply_result, vacancy)

            assert "Tech Corp" in job_applier.skipped_companies
            saved_job = job_applier.skipped_companies["Tech Corp"][0]
            assert saved_job["company_name"] == "Tech Corp"

    def test_save_company_persists_evaluation_metadata(self, job_applier):
        with patch.object(job_applier, "_save_company_to_yaml"):
            job_applier.success_companies = {}
            job_applier.skipped_companies = {}
            job_applier.failed_companies = {}

            job = Job(
                job_title="Software Engineer",
                company_name="Tech Corp",
                url="https://linkedin.com/jobs/view/12345",
            )

            job_applier._save_company(
                job,
                ("Skip", "Not interesting"),
                {"url": "https://linkedin.com/jobs/view/12345"},
                evaluation={
                    "interest_score": 42,
                    "interest_reason": "Mismatch with role target",
                    "skills": ["Python", "Leadership"],
                    "submitted_resume_path": "/tmp/resume.pdf",
                    "applied_at": "2026-05-06T17:08:00",
                    "applied_at_text": "18 hours ago",
                },
            )

            saved_job = job_applier.skipped_companies["Tech Corp"][0]
            assert saved_job["interest_score"] == 42
            assert saved_job["interest_reason"] == "Mismatch with role target"
            assert saved_job["skills"] == ["Python", "Leadership"]
            assert saved_job["submitted_resume_path"] == "/tmp/resume.pdf"
            assert saved_job["applied_at"] == "2026-05-06T17:08:00"
            assert saved_job["applied_at_text"] == "18 hours ago"

    def test_save_company_skip_does_not_duplicate_existing_entry(self, job_applier):
        """Test duplicate skipped vacancies are not appended again"""
        with patch.object(job_applier, "_save_company_to_yaml") as mock_save:
            job_applier.success_companies = {}
            job_applier.skipped_companies = {
                "Tech Corp": [
                    {
                        "job_title": "Software Engineer",
                        "url": "https://linkedin.com/jobs/view/12345",
                        "skip_reason": "Not interesting",
                    }
                ]
            }
            job_applier.failed_companies = {}

            job = Job(
                job_title="Software Engineer",
                company_name="Tech Corp",
                url="https://linkedin.com/jobs/view/12345",
            )
            vacancy = {"url": "https://linkedin.com/jobs/view/12345"}
            apply_result = ("Skip", "Not interesting")

            job_applier._save_company(job, apply_result, vacancy)

            assert len(job_applier.skipped_companies["Tech Corp"]) == 1
            mock_save.assert_not_called()

    def test_save_company_failed(self, job_applier):
        """Test saving company to failed list"""
        with patch.object(job_applier, "_save_company_to_yaml"):
            job_applier.success_companies = {}
            job_applier.skipped_companies = {}
            job_applier.failed_companies = {}

            job = Job(
                job_title="Software Engineer",
                company_name="Tech Corp",
                url="https://linkedin.com/jobs/view/12345",
            )
            vacancy = {"url": "https://linkedin.com/jobs/view/12345"}
            apply_result = ("Error", "Form submission failed")

            job_applier._save_company(job, apply_result, vacancy)

            assert "Tech Corp" in job_applier.failed_companies

    def test_load_companies_from_yaml_not_found(self, job_applier):
        """Test loading companies when file doesn't exist"""
        with patch("builtins.open", side_effect=FileNotFoundError):
            result = job_applier._load_companies_from_yaml("nonexistent.yaml")

            assert result == {}

    def test_load_companies_from_yaml_success(self, job_applier):
        """Test loading companies from existing file"""
        companies_data = {
            "Tech Corp": [{"job_title": "Engineer", "url": "http://test.com"}],
            "Another Corp": [{"job_title": "Developer", "url": "http://test2.com"}],
        }

        with (
            patch("builtins.open", mock_open()),
            patch("yaml.safe_load", return_value=companies_data),
        ):
            result = job_applier._load_companies_from_yaml("success.yaml")

            assert result == companies_data
            assert "Tech Corp" in result
            assert "Another Corp" in result


class TestJobSeenChecking:
    """Test job duplicate detection"""

    def test_job_is_already_seen_not_seen(self, job_applier):
        """Test when job has not been seen before"""
        job_applier.success_companies = {}
        job_applier.skipped_companies = {}
        job_applier.failed_companies = {}
        job_applier.apply_once_at_company = True

        job = Job(job_title="Software Engineer", company_name="New Company")

        is_seen, reason = job_applier._job_is_already_seen(job)

        assert is_seen is False
        assert reason == ""

    def test_job_is_already_seen_same_company_apply_once(self, job_applier):
        """Test when company was seen and apply_once_at_company is True"""
        job_applier.success_companies = {
            "Tech Corp": [{"job_title": "Other Position", "url": "http://test.com"}]
        }
        job_applier.skipped_companies = {}
        job_applier.failed_companies = {}
        job_applier.apply_once_at_company = True

        job = Job(job_title="Software Engineer", company_name="Tech Corp")

        with patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False):
            is_seen, reason = job_applier._job_is_already_seen(job)

        assert is_seen is True
        assert "company has already been encountered" in reason

    def test_job_is_already_seen_same_job_title(self, job_applier):
        """Test when same job title at same company was seen"""
        job_applier.success_companies = {
            "Tech Corp": [{"job_title": "Software Engineer", "url": "http://test.com"}]
        }
        job_applier.skipped_companies = {}
        job_applier.failed_companies = {}
        job_applier.apply_once_at_company = False
        job = Job(job_title="Software Engineer", company_name="Tech Corp")
        with patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False):
            is_seen, reason = job_applier._job_is_already_seen(job)

        assert is_seen is True
        assert "vacancy has already been encountered" in reason

    def test_job_is_already_seen_when_skipped_before(self, job_applier):
        """Test skipped jobs are treated as already seen"""
        job_applier.success_companies = {}
        job_applier.skipped_companies = {
            "Tech Corp": [{"job_title": "Software Engineer", "url": "http://test.com"}]
        }
        job_applier.failed_companies = {}
        job_applier.apply_once_at_company = False

        job = Job(job_title="Software Engineer", company_name="Tech Corp")

        with patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False):
            is_seen, reason = job_applier._job_is_already_seen(job)

        assert is_seen is True
        assert "vacancy has already been encountered" in reason

    def test_job_is_not_seen_when_failed_before(self, job_applier):
        """Test failed jobs are retried instead of treated as already seen"""
        job_applier.success_companies = {}
        job_applier.skipped_companies = {}
        job_applier.failed_companies = {
            "Tech Corp": [{"job_title": "Software Engineer", "url": "http://test.com"}]
        }
        job_applier.apply_once_at_company = True

        job = Job(job_title="Software Engineer", company_name="Tech Corp")

        with patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False):
            is_seen, reason = job_applier._job_is_already_seen(job)

        assert is_seen is False
        assert reason == ""


class TestPagination:
    """Test search result pagination"""

    @pytest.mark.asyncio
    async def test_go_to_next_page_does_not_increment_when_click_fails(self, job_applier):
        """Test page number stays unchanged if next page button is missing"""
        job_applier.page_num = 1

        with (
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.safe_click", new_callable=AsyncMock
            ) as mock_click,
            patch(
                "src.job_manager.linkedin.job_manager_linkedin.find_element_safely",
                new_callable=AsyncMock,
            ) as mock_find,
        ):
            mock_click.return_value = False
            mock_find.return_value = None

            result = await job_applier._go_to_next_page()

        assert result is False
        assert job_applier.page_num == 1

    @pytest.mark.asyncio
    async def test_go_to_next_page_increments_after_successful_click(self, job_applier):
        """Test page number advances only after a successful click"""
        job_applier.page_num = 1

        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.safe_click", new_callable=AsyncMock
        ) as mock_click:
            mock_click.return_value = True

            result = await job_applier._go_to_next_page()

        assert result is True
        assert job_applier.page_num == 2

    @pytest.mark.asyncio
    async def test_go_to_next_page_uses_human_page_number_for_numbered_buttons(self, job_applier):
        """Test numbered pagination targets the next human-visible page number"""
        job_applier.page_num = 0
        attempted_selectors = []
        expected_selector = "button[aria-label='Page 2']:not([disabled]):not([aria-current='page'])"

        async def safe_click_side_effect(page, selector, timeout=10000):
            attempted_selectors.append(selector)
            return selector == expected_selector

        with patch(
            "src.job_manager.linkedin.job_manager_linkedin.safe_click",
            side_effect=safe_click_side_effect,
        ):
            result = await job_applier._go_to_next_page()

        assert result is True
        assert job_applier.page_num == 1
        assert attempted_selectors[0] == expected_selector


class TestInterestingJobs:
    """Test interesting job saving"""

    def test_save_interesting_job(self, job_applier):
        """Test saving an interesting job"""
        with patch.object(job_applier, "_save_data_to_yaml") as mock_save:
            job_applier.interesting_jobs = []
            job_applier.job_key_skills = ["Python", "Docker"]

            job = Job(
                job_title="Senior Engineer",
                company_name="Tech Corp",
                url="https://linkedin.com/jobs/view/12345",
            )

            job_applier._save_interesting_job(job, score=85, reasoning="Great fit")

            assert len(job_applier.interesting_jobs) == 1
            saved_job = job_applier.interesting_jobs[0]
            assert saved_job.job_title == "Senior Engineer"
            assert saved_job.company_name == "Tech Corp"
            assert saved_job.interest_score == 85
            assert saved_job.interest_reason == "Great fit"
            assert saved_job.skills == ["Python", "Docker"]
            saved_payload = mock_save.call_args.args[0]
            assert "skip_reason" not in saved_payload[0]
            assert "applied_at" not in saved_payload[0]
            assert "applied_at_text" not in saved_payload[0]
            assert "submitted_resume_path" not in saved_payload[0]
            assert "executed_at" not in saved_payload[0]

    def test_save_interesting_job_sorted(self, job_applier):
        """Test that interesting jobs are sorted by score"""
        with patch.object(job_applier, "_save_data_to_yaml"):
            job_applier.interesting_jobs = []
            job_applier.job_key_skills = []

            job1 = Job(
                job_title="Job 1", company_name="Corp 1", url="https://linkedin.com/jobs/view/1"
            )
            job2 = Job(
                job_title="Job 2", company_name="Corp 2", url="https://linkedin.com/jobs/view/2"
            )
            job3 = Job(
                job_title="Job 3", company_name="Corp 3", url="https://linkedin.com/jobs/view/3"
            )

            job_applier._save_interesting_job(job1, score=70, reasoning="Good")
            job_applier._save_interesting_job(job2, score=90, reasoning="Excellent")
            job_applier._save_interesting_job(job3, score=80, reasoning="Very good")

            assert job_applier.interesting_jobs[0].interest_score == 90
            assert job_applier.interesting_jobs[1].interest_score == 80
            assert job_applier.interesting_jobs[2].interest_score == 70


class TestDataPersistence:
    """Test data saving and loading"""

    def test_save_data_to_yaml(self, job_applier):
        """Test saving data to YAML file without real I/O"""
        data = {"key1": "value1", "key2": "value2"}
        mock_path = Path("/mock/output/test_data.yaml")

        with (
            patch.object(job_applier, "_define_output_file", return_value=mock_path),
            patch("builtins.open", mock_open()),
            patch("src.job_manager.job_manager.save_yaml_file") as mock_save,
        ):
            job_applier._save_data_to_yaml(data, "test_data.yaml")

            mock_save.assert_called_once()
            args, kwargs = mock_save.call_args
            assert args[0] == mock_path
            assert args[1] == data

    def test_load_data_from_yaml_success(self, job_applier):
        """Test loading data from YAML file without real I/O"""
        data = {"key1": "value1", "key2": "value2"}
        mock_path = Path("/mock/output/test_data.yaml")

        with (
            patch.object(job_applier, "_define_output_file", return_value=mock_path),
            patch("builtins.open", mock_open()),
            patch("yaml.safe_load", return_value=data),
        ):
            loaded_data = job_applier._load_data_from_yaml("test_data.yaml")

            assert loaded_data == data

    def test_load_data_from_yaml_not_found(self, job_applier):
        """Test loading data when file doesn't exist (no I/O)"""
        with patch("builtins.open", side_effect=FileNotFoundError):
            loaded_data = job_applier._load_data_from_yaml("nonexistent.yaml")

            assert loaded_data == {}

    def test_load_data_from_yaml_answers_returns_list(self, job_applier):
        """Test that loading answers.yaml returns list when file not found (no I/O)"""
        mock_path = Path("/mock/output/nonexistent_answers.yaml")

        with (
            patch.object(job_applier, "_define_output_file", return_value=mock_path),
            patch("builtins.open", side_effect=FileNotFoundError),
        ):
            loaded_data = job_applier._load_data_from_yaml("answers.yaml")

            assert loaded_data == []

    def test_load_data_from_yaml_empty_interesting_jobs_returns_list(self, job_applier):
        """Test that an empty interesting_jobs.yaml is treated as no interesting jobs."""
        mock_path = Path("/mock/output/interesting_jobs.yaml")

        with (
            patch.object(job_applier, "_define_output_file", return_value=mock_path),
            patch("builtins.open", mock_open(read_data="")),
            patch("yaml.safe_load", return_value=None),
        ):
            loaded_data = job_applier._load_data_from_yaml("interesting_jobs.yaml")

            assert loaded_data == []

    def test_load_data_from_yaml_empty_mapping_file_returns_dict(self, job_applier):
        """Test that empty company/status YAML files are treated as no companies."""
        mock_path = Path("/mock/output/skipped.yaml")

        with (
            patch.object(job_applier, "_define_output_file", return_value=mock_path),
            patch("builtins.open", mock_open(read_data="")),
            patch("yaml.safe_load", return_value=None),
        ):
            loaded_data = job_applier._load_data_from_yaml("skipped.yaml")

            assert loaded_data == {}


class TestDefineOutputFile:
    """Test output file path definition"""

    def test_define_output_file(self):
        """Test defining output file path"""
        result = LinkedInJobManager._define_output_file("test.yaml")

        # Just verify it returns a path containing the filename
        assert "test.yaml" in str(result)
        assert "data/output" in str(result) or "data\\output" in str(result)


class TestExtractSkillsFromVacancy:
    """Test skills extraction from vacancy"""

    def test_extract_skills_from_vacancy(self, job_applier):
        """Test extracting skills from vacancy using LLM"""
        mock_llm_answerer = MagicMock()
        mock_llm_answerer.extract_skills_from_vacancy.return_value = [
            "Python",
            "Docker",
            "Kubernetes",
        ]
        job_applier.llm_answerer_component = mock_llm_answerer

        job = Job(
            job_description="We are looking for a developer with Python, Docker, and Kubernetes experience"
        )

        job_applier._extract_skills_from_vacancy(job)

        assert job_applier.job_key_skills == ["Python", "Docker", "Kubernetes"]
        mock_llm_answerer.extract_skills_from_vacancy.assert_called_once_with(job.job_description)


class TestHandleApplyResult:
    """Test _handle_apply_result async method"""

    @pytest.mark.asyncio
    async def test_handle_apply_result_success(self, job_applier):
        job_applier.applies_num = 0
        job_applier.success_applies_num = 0
        job_applier.total_applies_num = 0
        job_applier.error_num = 0
        job_applier.cache = JobManagerCache()

        job = Job(
            job_title="Software Engineer",
            company_name="Tech Corp",
            url="https://linkedin.com/jobs/view/1",
        )

        with (
            patch("src.job_manager.job_manager.emit_event"),
            patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False),
            patch.object(job_applier, "_save_company"),
            patch.object(job_applier, "_write_the_last_search_time"),
        ):
            await job_applier._handle_apply_result(("Success", ""), job)

        assert job_applier.applies_num == 1
        assert job_applier.success_applies_num == 1
        assert job_applier.total_applies_num == 1
        assert job_applier.error_num == 0

    @pytest.mark.asyncio
    async def test_handle_apply_result_passes_evaluation_to_save_company(self, job_applier):
        job_applier.applies_num = 0
        job_applier.success_applies_num = 0
        job_applier.total_applies_num = 0
        job_applier.error_num = 0
        job_applier.cache = JobManagerCache()

        job = Job(
            job_title="Software Engineer",
            company_name="Tech Corp",
            url="https://linkedin.com/jobs/view/1",
        )

        with (
            patch("src.job_manager.job_manager.emit_event"),
            patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False),
            patch.object(job_applier, "_save_company") as mock_save,
            patch.object(job_applier, "_write_the_last_search_time"),
        ):
            await job_applier._handle_apply_result(
                ("Success", ""),
                job,
                evaluation={
                    "interest_score": 88,
                    "interest_reason": "Strong fit",
                    "skills": ["Python"],
                },
            )

        mock_save.assert_called_once_with(
            job,
            ("Success", ""),
            {"url": job.url},
            evaluation={
                "interest_score": 88,
                "interest_reason": "Strong fit",
                "skills": ["Python"],
            },
        )

    @pytest.mark.asyncio
    async def test_handle_apply_result_error(self, job_applier):
        job_applier.applies_num = 0
        job_applier.success_applies_num = 0
        job_applier.total_applies_num = 0
        job_applier.error_num = 0
        job_applier.cache = JobManagerCache()

        job = Job(
            job_title="Software Engineer",
            company_name="Tech Corp",
            url="https://linkedin.com/jobs/view/1",
        )

        with (
            patch("src.job_manager.job_manager.emit_event"),
            patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False),
            patch.object(job_applier, "_save_company"),
        ):
            await job_applier._handle_apply_result(("Error", "Form failed"), job)

        assert job_applier.applies_num == 1
        assert job_applier.error_num == 1
        assert job_applier.success_applies_num == 0

    @pytest.mark.asyncio
    async def test_handle_apply_result_no_info_skip_saved_as_interesting(self, job_applier):
        job_applier.applies_num = 0
        job_applier.success_applies_num = 0
        job_applier.total_applies_num = 0
        job_applier.error_num = 0
        job_applier.cache = JobManagerCache()

        job = Job(
            job_title="Software Engineer",
            company_name="Tech Corp",
            url="https://linkedin.com/jobs/view/1",
        )
        apply_result = (
            "Skip",
            "Could not apply to Software Engineer at Tech Corp. Reason: No info found for question: salary",
        )

        with (
            patch("src.job_manager.job_manager.emit_event"),
            patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False),
            patch.object(job_applier, "_save_company") as mock_save_company,
            patch.object(job_applier, "_save_interesting_job") as mock_save_interesting,
        ):
            await job_applier._handle_apply_result(
                apply_result,
                job,
                evaluation={"interest_score": 82, "interest_reason": "Strong fit"},
            )

        mock_save_company.assert_not_called()
        mock_save_interesting.assert_called_once_with(job, score=82, reasoning=apply_result[1])

    @pytest.mark.asyncio
    async def test_handle_apply_result_easy_apply_dialog_skip_saved_as_interesting(
        self, job_applier
    ):
        job_applier.applies_num = 0
        job_applier.success_applies_num = 0
        job_applier.total_applies_num = 0
        job_applier.error_num = 0
        job_applier.cache = JobManagerCache()

        job = Job(
            job_title="Software Engineer",
            company_name="Tech Corp",
            url="https://linkedin.com/jobs/view/1",
        )
        apply_result = (
            "Skip",
            "Could not apply to Software Engineer at Tech Corp. Reason: Easy Apply dialog did not open",
        )

        with (
            patch("src.job_manager.job_manager.emit_event"),
            patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False),
            patch.object(job_applier, "_save_company") as mock_save_company,
            patch.object(job_applier, "_save_interesting_job") as mock_save_interesting,
        ):
            await job_applier._handle_apply_result(apply_result, job)

        mock_save_company.assert_not_called()
        mock_save_interesting.assert_called_once_with(job, score=0, reasoning=apply_result[1])

    @pytest.mark.asyncio
    async def test_handle_apply_result_limit_does_not_save_company(self, job_applier):
        job_applier.applies_num = 0
        job_applier.success_applies_num = 0
        job_applier.total_applies_num = 0
        job_applier.error_num = 0
        job_applier.cache = JobManagerCache()

        job = Job(
            job_title="Software Engineer",
            company_name="Tech Corp",
            url="https://linkedin.com/jobs/view/1",
        )

        with (
            patch("src.job_manager.job_manager.emit_event"),
            patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False),
            patch.object(job_applier, "_save_company") as mock_save,
        ):
            await job_applier._handle_apply_result(("Limit", ""), job)

        mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_apply_result_collect_info_mode_does_not_save_company(self, job_applier):
        job_applier.applies_num = 0
        job_applier.success_applies_num = 0
        job_applier.total_applies_num = 0
        job_applier.error_num = 0
        job_applier.cache = JobManagerCache()

        job = Job(
            job_title="Software Engineer",
            company_name="Tech Corp",
            url="https://linkedin.com/jobs/view/1",
        )

        with (
            patch("src.job_manager.job_manager.emit_event"),
            patch("src.job_manager.job_manager.COLLECT_INFO_MODE", True),
            patch.object(job_applier, "_save_company") as mock_save,
        ):
            await job_applier._handle_apply_result(("Success", ""), job)

        mock_save.assert_not_called()


class TestSendReport:
    """Test send_report async method"""

    @pytest.mark.asyncio
    async def test_send_report_skipped_in_test_mode(self, job_applier):
        job_applier.previous_apply_number = 0
        job_applier.success_applies_num = 5

        with (
            patch("src.job_manager.job_manager.TEST_MODE", True),
            patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False),
            patch("src.telegram.telegram_manager.TelegramReportSender") as mock_bot,
        ):
            await job_applier.send_report("Success")

        mock_bot.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_report_skipped_in_collect_info_mode(self, job_applier):
        job_applier.previous_apply_number = 0
        job_applier.success_applies_num = 5

        with (
            patch("src.job_manager.job_manager.TEST_MODE", False),
            patch("src.job_manager.job_manager.COLLECT_INFO_MODE", True),
            patch("src.telegram.telegram_manager.TelegramReportSender") as mock_bot,
        ):
            await job_applier.send_report("Success")

        mock_bot.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_report_skipped_on_error_result(self, job_applier):
        job_applier.previous_apply_number = 0
        job_applier.success_applies_num = 5

        with (
            patch("src.job_manager.job_manager.TEST_MODE", False),
            patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False),
            patch("src.telegram.telegram_manager.TelegramReportSender") as mock_bot,
        ):
            await job_applier.send_report("Error")

        mock_bot.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_report_skipped_when_no_new_applies(self, job_applier):
        job_applier.previous_apply_number = 5
        job_applier.success_applies_num = 5

        with (
            patch("src.job_manager.job_manager.TEST_MODE", False),
            patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False),
            patch("src.telegram.telegram_manager.TelegramReportSender") as mock_bot,
        ):
            await job_applier.send_report("Success")

        mock_bot.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_report_sends_when_conditions_met(self, job_applier):
        job_applier.previous_apply_number = 0
        job_applier.success_applies_num = 3
        job_applier.jobs_no_info = []
        job_applier.skill_stat = {}
        job_applier.resume = {}
        job_applier.resume_recommendations = ""
        job_applier.email = "test@example.com"

        mock_bot_instance = MagicMock()
        mock_bot_instance.send_telegram_report = AsyncMock()

        with (
            patch("src.job_manager.job_manager.TEST_MODE", False),
            patch("src.job_manager.job_manager.COLLECT_INFO_MODE", False),
            patch(
                "src.job_manager.job_manager.TelegramReportSender",
                return_value=mock_bot_instance,
            ),
            patch.object(job_applier, "_write_the_last_search_time"),
        ):
            await job_applier.send_report("Success")

        mock_bot_instance.send_telegram_report.assert_called_once()


class TestResumeImprovementRecommendations:
    """Test resume_improvement_recommendations method"""

    def test_loads_from_file_if_exists(self, job_applier):
        job_applier.llm_answerer_component = MagicMock()

        with (
            patch.object(
                job_applier, "_define_output_file", return_value=Path("/mock/resume_recs.txt")
            ),
            patch("builtins.open", mock_open(read_data="Existing recommendations")),
        ):
            job_applier.resume_improvement_recommendations()

        assert job_applier.resume_recommendations == "Existing recommendations"
        job_applier.llm_answerer_component.resume_improvement_recommendations.assert_not_called()

    def test_generates_if_file_empty(self, job_applier):
        job_applier.llm_answerer_component = MagicMock()
        job_applier.llm_answerer_component.resume_improvement_recommendations.return_value = (
            "New recommendations"
        )
        job_applier.resume_anonymizer.deanonymize_text = lambda text: text

        mock_file = mock_open(read_data="")
        with (
            patch.object(
                job_applier, "_define_output_file", return_value=Path("/mock/resume_recs.txt")
            ),
            patch("builtins.open", mock_file),
        ):
            job_applier.resume_improvement_recommendations()

        assert job_applier.resume_recommendations == "New recommendations"
        job_applier.llm_answerer_component.resume_improvement_recommendations.assert_called_once()

    def test_generates_if_file_not_found(self, job_applier):
        job_applier.llm_answerer_component = MagicMock()
        job_applier.llm_answerer_component.resume_improvement_recommendations.return_value = (
            "New recommendations"
        )
        job_applier.resume_anonymizer.deanonymize_text = lambda text: text

        def open_side_effect(path, mode="r", **kwargs):
            if "r" in mode:
                raise FileNotFoundError
            return mock_open()()

        with (
            patch.object(
                job_applier, "_define_output_file", return_value=Path("/mock/resume_recs.txt")
            ),
            patch("builtins.open", side_effect=open_side_effect),
        ):
            job_applier.resume_improvement_recommendations()

        assert job_applier.resume_recommendations == "New recommendations"


class TestCheckLastSearchTimeWithPreviousApply:
    """Test check_the_last_search_time edge cases"""

    def test_check_too_soon_but_previous_apply_number_nonzero(self, job_applier):
        """When last run < 24h ago but previous_apply_number > 0, should return True"""
        recent_time = datetime.now() - timedelta(hours=12)
        job_applier.cache = JobManagerCache(last_run=recent_time.isoformat())
        job_applier.previous_apply_number = 3

        result = job_applier.check_the_last_search_time()

        assert result is True


class TestJobIsAlreadySeenCollectInfoMode:
    """Test _job_is_already_seen in COLLECT_INFO_MODE"""

    def test_job_is_already_seen_in_collect_info_mode(self, job_applier):
        from src.pydantic_models.job_models import JobInfo

        job_applier.interesting_jobs = [
            JobInfo(job_title="Software Engineer", company_name="Tech Corp")
        ]

        job = Job(job_title="Software Engineer", company_name="Tech Corp")

        with patch("src.job_manager.job_manager.COLLECT_INFO_MODE", True):
            is_seen, reason = job_applier._job_is_already_seen(job)

        assert is_seen is True
        assert "vacancy has already been encountered" in reason

    def test_job_not_seen_in_collect_info_mode(self, job_applier):
        from src.pydantic_models.job_models import JobInfo

        job_applier.interesting_jobs = [JobInfo(job_title="Other Job", company_name="Other Corp")]

        job = Job(job_title="Software Engineer", company_name="Tech Corp")

        with patch("src.job_manager.job_manager.COLLECT_INFO_MODE", True):
            is_seen, reason = job_applier._job_is_already_seen(job)

        assert is_seen is False
        assert reason == ""


class TestSaveCompanyEdgeCases:
    """Test _save_company edge cases"""

    def test_save_company_empty_name_does_not_save(self, job_applier):
        with patch.object(job_applier, "_save_company_to_yaml") as mock_save:
            job_applier.success_companies = {}
            job_applier.skipped_companies = {}
            job_applier.failed_companies = {}

            job = Job(
                job_title="Software Engineer",
                company_name="",
                url="https://linkedin.com/jobs/view/1",
            )
            job_applier._save_company(job, ("Success", ""), {"url": job.url})

            assert job_applier.success_companies == {}
            mock_save.assert_called_once()

    def test_save_company_appends_to_existing(self, job_applier):
        with patch.object(job_applier, "_save_company_to_yaml"):
            job_applier.success_companies = {
                "Tech Corp": [{"job_title": "Backend Engineer", "url": "http://test.com"}]
            }
            job_applier.skipped_companies = {}
            job_applier.failed_companies = {}

            job = Job(
                job_title="Frontend Engineer",
                company_name="Tech Corp",
                url="https://linkedin.com/jobs/view/2",
            )
            job_applier._save_company(job, ("Success", ""), {"url": job.url})

            assert len(job_applier.success_companies["Tech Corp"]) == 2
