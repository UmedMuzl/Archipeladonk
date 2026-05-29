"""Unit tests for emu_loader.utils."""

import pytest

from emu_loader.utils import sanitize_and_trim


class TestSanitizeAndTrim:
    def test_basic_string_uppercased(self):
        assert sanitize_and_trim("hello") == "HELLO"

    def test_strips_apostrophe(self):
        assert sanitize_and_trim("don't") == "DONT"

    def test_strips_backtick(self):
        assert sanitize_and_trim("foo`bar") == "FOOBAR"

    def test_strips_right_single_quotation_mark(self):
        # U+2019 RIGHT SINGLE QUOTATION MARK
        assert sanitize_and_trim("it\u2019s") == "ITS"

    def test_strips_non_alphanumeric_except_space(self):
        assert sanitize_and_trim("hello! world@#") == "HELLO WORLD"

    def test_preserves_spaces(self):
        assert sanitize_and_trim("mario 64") == "MARIO 64"

    def test_trims_leading_trailing_whitespace(self):
        assert sanitize_and_trim("  hello  ") == "HELLO"

    def test_default_max_length_31(self):
        long_string = "a" * 50
        result = sanitize_and_trim(long_string)
        assert len(result) == 31

    def test_custom_max_length(self):
        result = sanitize_and_trim("abcdefghij", max_length=5)
        assert result == "ABCDE"

    def test_empty_string(self):
        assert sanitize_and_trim("") == ""

    def test_only_special_chars_returns_empty(self):
        assert sanitize_and_trim("!!!@@@###") == ""

    def test_numbers_preserved(self):
        assert sanitize_and_trim("level99") == "LEVEL99"
