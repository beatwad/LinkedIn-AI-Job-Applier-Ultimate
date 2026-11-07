"""Test suite for src/utils/utils.py"""

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.utils.utils import (
    ConfigError,
    clean_structured_resume,
    debug_page_elements,
    detect_text_language,
    format_missing_fields_display,
    get_resume_for_job_language,
    get_user_choice_with_timeout,
    load_yaml_file,
    pause,
    sanitize_text,
    save_yaml_file,
    sleep,
    validate_and_prompt_resume_completion,
    validate_structured_resume_fields,
)


class TestLoadYamlFile:
    """Tests for load_yaml_file function"""

    def test_load_valid_yaml_file(self, tmp_path):
        """Test loading a valid YAML file"""
        yaml_file = tmp_path / "test.yaml"
        test_data = {"key": "value", "number": 42, "list": [1, 2, 3]}

        # Write test data
        with open(yaml_file, "w", encoding="UTF-8") as f:
            yaml.safe_dump(test_data, f)

        # Load and verify
        result = load_yaml_file(yaml_file)
        assert result == test_data

    def test_load_yaml_file_not_found(self):
        """Test loading a non-existent YAML file"""
        with pytest.raises(ConfigError, match="File not found"):
            load_yaml_file(Path("/nonexistent/file.yaml"))

    def test_load_invalid_yaml_file(self, tmp_path):
        """Test loading an invalid YAML file"""
        yaml_file = tmp_path / "invalid.yaml"

        # Write invalid YAML
        with open(yaml_file, "w", encoding="UTF-8") as f:
            f.write("invalid: yaml: content: [\n")

        with pytest.raises(yaml.YAMLError, match="Error in reading file"):
            load_yaml_file(yaml_file)

    def test_load_empty_yaml_file(self, tmp_path):
        """Test loading an empty YAML file"""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.touch()

        result = load_yaml_file(yaml_file)
        assert result is None


class TestSaveYamlFile:
    """Tests for save_yaml_file function"""

    def test_save_yaml_file(self, tmp_path):
        """Test saving data to YAML file"""
        yaml_file = tmp_path / "output.yaml"
        test_data = {"name": "John", "age": 30, "skills": ["Python", "JavaScript"]}

        save_yaml_file(yaml_file, test_data)

        # Read back and verify
        with open(yaml_file, "r", encoding="UTF-8") as f:
            loaded_data = yaml.safe_load(f)

        assert loaded_data == test_data

    def test_save_yaml_file_with_unicode(self, tmp_path):
        """Test saving YAML file with Unicode characters"""
        yaml_file = tmp_path / "unicode.yaml"
        test_data = {"name": "José", "city": "São Paulo", "greeting": "こんにちは"}

        save_yaml_file(yaml_file, test_data)

        # Read back and verify
        with open(yaml_file, "r", encoding="UTF-8") as f:
            loaded_data = yaml.safe_load(f)

        assert loaded_data == test_data

    def test_save_yaml_file_overwrite(self, tmp_path):
        """Test overwriting an existing YAML file"""
        yaml_file = tmp_path / "overwrite.yaml"

        # Write initial data
        initial_data = {"old": "data"}
        save_yaml_file(yaml_file, initial_data)

        # Overwrite with new data
        new_data = {"new": "data"}
        save_yaml_file(yaml_file, new_data)

        # Verify new data
        with open(yaml_file, "r", encoding="UTF-8") as f:
            loaded_data = yaml.safe_load(f)

        assert loaded_data == new_data
        assert loaded_data != initial_data

    @patch("src.utils.utils.os.fsync")
    def test_save_yaml_file_flushes_file_and_directory(self, mock_fsync, tmp_path):
        """Test YAML saves are flushed so per-job output survives abrupt shutdowns"""
        yaml_file = tmp_path / "output.yaml"

        save_yaml_file(yaml_file, {"status": "saved"})

        assert yaml_file.exists()
        assert mock_fsync.call_count >= 2
        assert list(tmp_path.glob("*.tmp")) == []


class TestPause:
    """Tests for pause function"""

    def test_pause_default_range(self):
        """Test pause with default range"""
        start = time.time()
        pause()
        elapsed = time.time() - start

        # Should be between 0.5 and 1 second
        assert 0.4 <= elapsed <= 1.2  # Allow small margin for execution time

    def test_pause_custom_range(self):
        """Test pause with custom range"""
        start = time.time()
        pause(0.1, 0.2)
        elapsed = time.time() - start

        # Should be between 0.1 and 0.2 seconds
        assert 0.05 <= elapsed <= 0.3  # Allow small margin

    def test_pause_zero_range(self):
        """Test pause with zero range"""
        start = time.time()
        pause(0, 0)
        elapsed = time.time() - start

        # Should be very close to 0
        assert elapsed < 0.1


class TestSleep:
    """Tests for sleep function"""

    @patch("src.utils.utils.time.sleep")
    @patch("src.utils.utils.logger")
    def test_sleep_with_interval(self, mock_logger, mock_time_sleep):
        """Test sleep with specified interval"""
        sleep((60, 120))

        # Verify sleep was called
        mock_time_sleep.assert_called_once()
        sleep_time = mock_time_sleep.call_args[0][0]

        # Should be between 60 and 120 seconds
        assert 60 <= sleep_time <= 120

        # Verify logging
        mock_logger.info.assert_called_once()
        log_message = mock_logger.info.call_args[0][0]
        assert "Waiting lasted" in log_message

    @patch("src.utils.utils.time.sleep")
    @patch("src.utils.utils.logger")
    def test_sleep_with_short_interval(self, mock_logger, mock_time_sleep):
        """Test sleep with short interval"""
        sleep((5, 10))

        mock_time_sleep.assert_called_once()
        sleep_time = mock_time_sleep.call_args[0][0]
        assert 5 <= sleep_time <= 10


class TestSanitizeText:
    """Tests for sanitize_text function"""

    def test_sanitize_basic_text(self):
        """Test sanitizing basic text"""
        result = sanitize_text("Hello World")
        assert result == "hello world"

    def test_sanitize_text_with_quotes(self):
        """Test sanitizing text with quotes"""
        result = sanitize_text('Text with "quotes"')
        assert result == "text with quotes"

    def test_sanitize_text_with_backslashes(self):
        """Test sanitizing text with backslashes"""
        result = sanitize_text(r"Text\with\backslashes")
        assert result == "textwithbackslashes"

    def test_sanitize_text_with_newlines(self):
        """Test sanitizing text with newlines and carriage returns"""
        # Note: \n and \r are control characters (0x0A and 0x0D) which are removed
        # by re.sub(r"[\x00-\x1F\x7F]", "", text) before the replace operations
        result = sanitize_text("Line 1\nLine 2\rLine 3")
        assert result == "line 1line 2line 3"

    def test_sanitize_text_with_multiple_spaces(self):
        """Test sanitizing text with multiple spaces"""
        result = sanitize_text("Text   with    multiple     spaces")
        assert result == "text with multiple spaces"

    def test_sanitize_text_with_trailing_comma(self):
        """Test sanitizing text with trailing comma"""
        result = sanitize_text("Text with comma,")
        assert result == "text with comma"

    def test_sanitize_text_with_control_characters(self):
        """Test sanitizing text with control characters"""
        result = sanitize_text("Text\x00with\x1fcontrol\x7fchars")
        assert result == "textwithcontrolchars"

    def test_sanitize_empty_text(self):
        """Test sanitizing empty text"""
        result = sanitize_text("")
        assert result == ""

    def test_sanitize_text_with_leading_trailing_spaces(self):
        """Test sanitizing text with leading/trailing spaces"""
        result = sanitize_text("  Text with spaces  ")
        assert result == "text with spaces"


class TestValidateStructuredResumeFields:
    """Tests for validate_structured_resume_fields function"""

    def test_validate_complete_resume(self):
        """Test validating a complete resume with no missing fields"""
        resume = {
            "personal_information": {"name": "John Doe", "email": "john@example.com"},
            "experience_details": [{"position": "Developer", "company": "Tech Corp", "years": 3}],
        }

        missing_fields = validate_structured_resume_fields(resume)
        assert missing_fields == []

    def test_validate_resume_with_placeholder_brackets(self):
        """Test validating resume with bracket placeholders"""
        resume = {
            "personal_information": {
                "name": "[Your Name]",
                "email": "john@example.com",
            }
        }

        missing_fields = validate_structured_resume_fields(resume)
        assert "personal_information.name" in missing_fields

    def test_validate_resume_with_no_info(self):
        """Test validating resume with 'No info' values"""
        resume = {"personal_information": {"name": "John Doe", "phone": "No info"}}

        missing_fields = validate_structured_resume_fields(resume)
        assert "personal_information.phone" in missing_fields

    def test_validate_resume_with_empty_string(self):
        """Test validating resume with empty strings"""
        resume = {"personal_information": {"name": "John Doe", "address": ""}}

        missing_fields = validate_structured_resume_fields(resume)
        assert "personal_information.address" in missing_fields

    def test_validate_resume_with_none_values(self):
        """Test validating resume with None values"""
        resume = {"personal_information": {"name": "John Doe", "linkedin": None}}

        missing_fields = validate_structured_resume_fields(resume)
        assert "personal_information.linkedin" in missing_fields

    def test_validate_resume_with_nested_lists(self):
        """Test validating resume with lists"""
        resume = {
            "experience_details": [
                {"position": "Developer", "company": "[Company Name]"},
                {"position": "Manager", "company": "Tech Inc"},
            ]
        }

        missing_fields = validate_structured_resume_fields(resume)
        assert "experience_details.1.company" in missing_fields

    def test_validate_empty_resume(self):
        """Test validating empty resume"""
        resume = {}
        missing_fields = validate_structured_resume_fields(resume)
        assert missing_fields == []


class TestFormatMissingFieldsDisplay:
    """Tests for format_missing_fields_display function"""

    def test_format_no_missing_fields(self):
        """Test formatting with no missing fields"""
        result = format_missing_fields_display([])
        assert result == "All fields are properly filled!"

    def test_format_single_missing_field(self):
        """Test formatting with single missing field"""
        missing_fields = ["personal_information.name"]
        result = format_missing_fields_display(missing_fields)

        assert "Missing or placeholder fields found" in result
        assert "📋 Personal Information:" in result
        assert "• Name" in result

    def test_format_multiple_missing_fields_same_section(self):
        """Test formatting with multiple missing fields in same section"""
        missing_fields = ["personal_information.name", "personal_information.email"]
        result = format_missing_fields_display(missing_fields)

        assert "Personal Information:" in result
        assert "• Name" in result
        assert "• Email" in result

    def test_format_multiple_sections(self):
        """Test formatting with missing fields in multiple sections"""
        missing_fields = [
            "personal_information.name",
            "experience_details.position",
            "education_details.degree",
        ]
        result = format_missing_fields_display(missing_fields)

        assert "Personal Information:" in result
        assert "Experience Details:" in result
        assert "Education Details:" in result


class TestGetUserChoiceWithTimeout:
    """Tests for get_user_choice_with_timeout function"""

    @patch("builtins.input", return_value="1")
    def test_get_user_choice_option_1(self, mock_input):
        """Test getting user choice option 1"""
        result = get_user_choice_with_timeout(1)
        assert result == "1"

    @patch("builtins.input", return_value="2")
    def test_get_user_choice_option_2(self, mock_input):
        """Test getting user choice option 2"""
        result = get_user_choice_with_timeout(1)
        assert result == "2"

    @patch("builtins.input", side_effect=EOFError)
    def test_get_user_choice_eof_error(self, mock_input):
        """Test handling EOFError"""
        result = get_user_choice_with_timeout(1)
        assert result == "continue"

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_get_user_choice_keyboard_interrupt(self, mock_input):
        """Test handling KeyboardInterrupt"""
        result = get_user_choice_with_timeout(1)
        assert result == "continue"

    @patch("builtins.input", side_effect=lambda x: time.sleep(2))
    def test_get_user_choice_timeout(self, mock_input):
        """Test timeout when no input provided"""
        result = get_user_choice_with_timeout(0.5)
        assert result == "continue"


class TestValidateAndPromptResumeCompletion:
    """Tests for validate_and_prompt_resume_completion function"""

    @patch("src.utils.utils.logger")
    def test_validate_complete_resume_no_prompt(self, mock_logger, tmp_path):
        """Test with complete resume - should return True without prompting"""
        resume = {"personal_information": {"name": "John Doe", "email": "john@example.com"}}
        resume_file = tmp_path / "resume.yaml"
        text_file = tmp_path / "resume.txt"

        result = validate_and_prompt_resume_completion(resume, resume_file, text_file)

        assert result is True
        mock_logger.info.assert_any_call("Validating structured resume fields...")
        mock_logger.info.assert_any_call("✅ All structured resume fields are properly filled!")

    @patch("src.utils.utils.get_user_choice_with_timeout", return_value="n")
    @patch("src.utils.utils.logger")
    @patch("builtins.print")
    def test_validate_incomplete_resume_user_exits(
        self, mock_print, mock_logger, mock_choice, tmp_path
    ):
        """Test with incomplete resume - user chooses to exit"""
        resume = {"personal_information": {"name": "[Your Name]"}}
        resume_file = tmp_path / "resume.yaml"
        text_file = tmp_path / "resume.txt"

        result = validate_and_prompt_resume_completion(resume, resume_file, text_file)

        assert result is False
        mock_choice.assert_called_once_with(30)
        mock_logger.info.assert_any_call("User chose to exit and edit structured resume file")

    @patch("src.utils.utils.get_user_choice_with_timeout", return_value="y")
    @patch("src.utils.utils.logger")
    @patch("builtins.print")
    def test_validate_incomplete_resume_user_continues(
        self, mock_print, mock_logger, mock_choice, tmp_path
    ):
        """Test with incomplete resume - user chooses to continue"""
        resume = {"personal_information": {"name": "[Your Name]"}}
        resume_file = tmp_path / "resume.yaml"
        text_file = tmp_path / "resume.txt"

        result = validate_and_prompt_resume_completion(resume, resume_file, text_file)

        assert result is True
        mock_choice.assert_called_once_with(30)
        mock_logger.info.assert_any_call("User chose to continue or timeout reached")

    @patch("src.utils.utils.get_user_choice_with_timeout", return_value="continue")
    @patch("src.utils.utils.logger")
    @patch("builtins.print")
    def test_validate_incomplete_resume_timeout(
        self, mock_print, mock_logger, mock_choice, tmp_path
    ):
        """Test with incomplete resume - timeout occurs"""
        resume = {"personal_information": {"name": ""}}
        resume_file = tmp_path / "resume.yaml"
        text_file = tmp_path / "resume.txt"

        result = validate_and_prompt_resume_completion(resume, resume_file, text_file)

        assert result is True
        mock_logger.info.assert_any_call("User chose to continue or timeout reached")


class TestDebugPageElements:
    """Tests for debug_page_elements function"""

    @patch("src.utils.utils.logger")
    def test_debug_page_elements_success(self, mock_logger):
        """Test debugging page elements successfully"""
        mock_page = MagicMock()
        mock_page.url = "https://example.com"

        # Mock modal elements
        modal_elem = MagicMock()
        modal_elem.get_attribute.return_value = "modal-dialog"

        # Mock easy-apply elements
        easy_apply_elem = MagicMock()
        easy_apply_elem.get_attribute.return_value = "easy-apply-button"

        # Mock form elements
        form_elem = MagicMock()
        form_elem.get_attribute.return_value = "application-form"

        mock_page.find_elements.side_effect = [
            [modal_elem],  # Modal elements
            [easy_apply_elem],  # Easy apply elements
            [form_elem],  # Form elements
        ]

        debug_page_elements(mock_page)

        # Verify logging calls
        assert mock_logger.debug.call_count >= 4
        mock_logger.debug.assert_any_call("=== DEBUGGING PAGE ELEMENTS ===")
        mock_logger.debug.assert_any_call("=== END DEBUGGING ===")

    @patch("src.utils.utils.logger")
    def test_debug_page_elements_with_exception(self, mock_logger):
        """Test debugging when exception occurs"""
        mock_page = MagicMock()
        mock_page.find_elements.side_effect = Exception("Test error")

        debug_page_elements(mock_page)

        # Should log error and continue
        mock_logger.debug.assert_any_call("=== DEBUGGING PAGE ELEMENTS ===")
        mock_logger.debug.assert_any_call("=== END DEBUGGING ===")


class TestCleanStructuredResume:
    """Tests for clean_structured_resume function"""

    def test_clean_resume_with_no_placeholders(self):
        """Test cleaning resume with no placeholders"""
        resume = {
            "personal_information": {"name": "John Doe", "email": "john@example.com"},
            "skills": ["Python", "JavaScript"],
        }

        result = clean_structured_resume(resume)
        assert result == resume

    def test_clean_resume_with_no_info(self):
        """Test cleaning resume with 'No info' values"""
        resume = {
            "personal_information": {
                "name": "John Doe",
                "phone": "No info",
                "email": "john@example.com",
            }
        }

        result = clean_structured_resume(resume)
        assert "phone" not in result["personal_information"]
        assert result["personal_information"]["name"] == "John Doe"
        assert result["personal_information"]["email"] == "john@example.com"

    def test_clean_resume_with_empty_strings(self):
        """Test cleaning resume with empty strings"""
        resume = {
            "personal_information": {
                "name": "John Doe",
                "address": "",
                "email": "john@example.com",
            }
        }

        result = clean_structured_resume(resume)
        assert "address" not in result["personal_information"]

    def test_clean_resume_with_none_values(self):
        """Test cleaning resume with None values"""
        resume = {
            "personal_information": {"name": "John Doe", "linkedin": None, "github": "johndoe"}
        }

        result = clean_structured_resume(resume)
        assert "linkedin" not in result["personal_information"]
        assert result["personal_information"]["github"] == "johndoe"

    def test_clean_resume_with_nested_structures(self):
        """Test cleaning resume with nested dictionaries and lists"""
        resume = {
            "experience_details": [
                {"position": "Developer", "company": "Tech Corp", "description": "No info"},
                {"position": "Manager", "company": "", "description": "Led team"},
                {"position": "No info", "company": "No info", "description": ""},
            ],
            "education_details": {"degree": "BS", "university": "", "gpa": None},
        }

        result = clean_structured_resume(resume)

        # First experience should have position and company only
        assert len(result["experience_details"]) == 2
        assert result["experience_details"][0]["position"] == "Developer"
        assert result["experience_details"][0]["company"] == "Tech Corp"
        assert "description" not in result["experience_details"][0]

        # Second experience should have position and description only
        assert result["experience_details"][1]["position"] == "Manager"
        assert result["experience_details"][1]["description"] == "Led team"
        assert "company" not in result["experience_details"][1]

        # Education should have degree only
        assert result["education_details"]["degree"] == "BS"
        assert "university" not in result["education_details"]
        assert "gpa" not in result["education_details"]

    def test_clean_resume_with_whitespace_strings(self):
        """Test cleaning resume with whitespace-only strings"""
        resume = {
            "personal_information": {
                "name": "John Doe",
                "title": "   ",
                "email": "  john@example.com  ",
            }
        }

        result = clean_structured_resume(resume)
        assert "title" not in result["personal_information"]
        assert result["personal_information"]["email"] == "john@example.com"

    def test_clean_empty_resume(self):
        """Test cleaning empty resume"""
        resume = {}
        result = clean_structured_resume(resume)
        assert result == {}

    def test_clean_resume_all_empty_sections(self):
        """Test cleaning resume where entire sections become empty"""
        resume = {
            "personal_information": {"name": "No info", "email": ""},
            "skills": [],
            "experience": [{"position": "", "company": "No info"}],
        }

        result = clean_structured_resume(resume)
        # All sections should be removed or empty
        assert "personal_information" not in result or result.get("personal_information") == {}
        assert "skills" not in result or result.get("skills") == []
        assert "experience" not in result or result.get("experience") == []

    def test_clean_resume_preserves_valid_data(self):
        """Test that cleaning preserves all valid data"""
        resume = {
            "personal_information": {
                "name": "Jane Smith",
                "email": "jane@example.com",
                "phone": "+1234567890",
                "linkedin": "linkedin.com/in/janesmith",
            },
            "experience_details": [
                {
                    "position": "Senior Developer",
                    "company": "Tech Corp",
                    "years": 5,
                    "achievements": ["Led team", "Improved performance"],
                }
            ],
            "skills": ["Python", "Java", "AWS"],
            "certifications": ["AWS Solutions Architect", "PMP"],
        }

        result = clean_structured_resume(resume)
        assert result == resume  # Should be unchanged


PT_DESCRIPTION = (
    "Estamos procurando uma pessoa desenvolvedora para a nossa equipe, com experiência em Node.js "
    "e que goste de trabalhar com filas, para atuar na construção de APIs e no desenvolvimento de "
    "novos produtos em uma empresa que valoriza o trabalho remoto e a colaboração entre os times."
)
ES_DESCRIPTION = (
    "Buscamos una persona desarrolladora para nuestro equipo, con experiencia en Node.js y que le "
    "guste trabajar con colas, para el desarrollo de APIs y nuevos productos en una empresa que "
    "valora el trabajo remoto y la colaboración entre los equipos del puesto."
)
EN_DESCRIPTION = (
    "We are looking for a senior engineer to join our team, with experience in Node.js and "
    "distributed systems, who will be responsible for building APIs and shipping new products "
    "for our customers in a fully remote company."
)


class TestDetectTextLanguage:
    """Tests for detect_text_language function"""

    @pytest.mark.parametrize(
        "text, expected",
        [(PT_DESCRIPTION, "pt"), (ES_DESCRIPTION, "es"), (EN_DESCRIPTION, "en")],
    )
    def test_detects_language(self, text, expected):
        assert detect_text_language(text) == expected

    def test_returns_none_for_short_text(self):
        assert detect_text_language("Senior Node.js engineer") is None


class TestGetResumeForJobLanguage:
    """Tests for get_resume_for_job_language function"""

    def test_returns_resume_for_detected_language(self, tmp_path):
        resume_pt = tmp_path / "resume_pt.pdf"
        resume_pt.write_bytes(b"pdf")
        with patch("src.utils.utils.READY_MADE_RESUME_PATHS_BY_LANGUAGE", {"pt": str(resume_pt)}):
            assert get_resume_for_job_language(PT_DESCRIPTION) == resume_pt.resolve()

    def test_returns_none_when_language_not_configured(self, tmp_path):
        resume_pt = tmp_path / "resume_pt.pdf"
        resume_pt.write_bytes(b"pdf")
        with patch("src.utils.utils.READY_MADE_RESUME_PATHS_BY_LANGUAGE", {"pt": str(resume_pt)}):
            assert get_resume_for_job_language(EN_DESCRIPTION) is None

    def test_returns_none_when_file_is_missing(self, tmp_path):
        with patch(
            "src.utils.utils.READY_MADE_RESUME_PATHS_BY_LANGUAGE",
            {"pt": str(tmp_path / "missing.pdf")},
        ):
            assert get_resume_for_job_language(PT_DESCRIPTION) is None

    def test_returns_none_without_mapping(self):
        with patch("src.utils.utils.READY_MADE_RESUME_PATHS_BY_LANGUAGE", {}):
            assert get_resume_for_job_language(PT_DESCRIPTION) is None
