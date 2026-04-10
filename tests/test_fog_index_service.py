"""
Test suite for fog_index service
Tests Flesch-Kincaid readability analysis functionality
"""
import pytest
import tempfile
from pathlib import Path
from src.services.fog_index import analyze_root, fog_index


class TestFogIndexService:
    """Test fog index readability analysis"""

    def test_fog_index_formula(self):
        """Test that the fog index score uses Flesch-Kincaid grade level."""
        text = "I don't have a cat. I have a dog."
        score = fog_index(text)
        assert score == pytest.approx(-2.035, abs=0.01)

    def test_analyze_root_ignores_markdown_and_reads_python_comments(self):
        """Test analyze_root ignores documentation and only returns code comment results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            readme_file = tmppath / "README.md"
            readme_file.write_text("This documentation should be ignored by the fog index scanner.")

            py_file = tmppath / "test.py"
            py_file.write_text(
                '"""\n'
                "This module docstring explains the purpose of the file.\n"
                "It contains enough words to be analyzed correctly.\n"
                '"""\n'
            )

            result = analyze_root(
                tmppath,
                high_threshold=12.0,
                low_threshold=6.0,
                min_comment_words=5,
                min_words=10,
            )

            assert isinstance(result, list)
            assert len(result) == 1
            assert all(isinstance(item, tuple) and len(item) == 5 for item in result)
            assert isinstance(result[0][0], (int, float))
            assert result[0][2] == "comment"
            assert Path(result[0][3]).name == "test.py"

    def test_analyze_root_with_python_comments(self):
        """Test fog index analysis with Python files containing docstrings"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # Create test Python file
            py_file = tmppath / "test.py"
            py_file.write_text(
                '''
                """
                This is a module docstring.
                It contains multiple lines of documentation.
                This helps understand what the module does.
                """

                def example_function():
                    """
                    Example function with docstring.
                    It demonstrates how docstrings work.
                    """
                    pass
                '''
            )

            result = analyze_root(
                tmppath,
                high_threshold=12.0,
                low_threshold=6.0,
                min_comment_words=5,
                min_words=10,
            )

            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0][2] == "comment"

    def test_analyze_root_with_empty_directory(self):
        """Test analyze_root with empty directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            result = analyze_root(tmppath, high_threshold=12.0, low_threshold=6.0, min_comment_words=5, min_words=10)
            
            assert isinstance(result, list)

    def test_analyze_root_with_short_comments(self):
        """Test that comments below min_words threshold are filtered"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            py_file = tmppath / "short.py"
            py_file.write_text("# Hi there.\n")

            result = analyze_root(
                tmppath,
                high_threshold=12.0,
                low_threshold=6.0,
                min_comment_words=5,
                min_words=10,
            )

            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0][1] == "ADD_MORE_TEXT"
            assert "comment words" in result[0][4]

    def test_analyze_root_thresholds(self):
        """Test that fog index correctly identifies high/low scores"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            complex_file = tmppath / "complex.py"
            complex_file.write_text(
                '"""\n'
                "The dichotomous multidisciplinary and multifunctional characteristics of contemporary epistemological frameworks necessitate comprehensive reexamination of our fundamental presuppositions regarding the acquisition of knowledge through phenomenological methodologies.\n"
                '"""\n'
            )

            result = analyze_root(
                tmppath,
                high_threshold=12.0,
                low_threshold=6.0,
                min_comment_words=5,
                min_words=10,
            )

            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0][0] > 12.0
            assert result[0][1] == "FLAG_HIGH_FOG"

    def test_fog_index_result_format(self):
        """Test that fog index returns results with correct format"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            py_file = tmppath / "test.py"
            py_file.write_text(
                '"""\n'
                "This is a test docstring for testing purposes.\n"
                "It contains meaningful content for analysis.\n"
                '"""\n'
            )

            result = analyze_root(
                tmppath,
                high_threshold=12.0,
                low_threshold=6.0,
                min_comment_words=5,
                min_words=10,
            )

            for item in result:
                score, status, kind, path, message = item
                assert isinstance(score, (int, float))
                assert status in ["OK", "FLAG_HIGH_FOG", "ADD_MORE_TEXT"]
                assert kind == "comment"
                assert isinstance(path, (str, Path))
                assert isinstance(message, str)

    def test_if_fog_index_is_low(self):
        """Test that a very easy sentence is still considered low threshold."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temppath = Path(tmpdir)
            py_file = temppath / "simple.py"
            py_file.write_text(
                '"""\n'
                "Cats run fast.\n"
                "Dogs jump high.\n"
                "Birds fly low.\n"
                "Fish swim near.\n"
                '"""\n'
            )

            result = analyze_root(
                temppath,
                high_threshold=12.0,
                low_threshold=5.0,
                min_comment_words=5,
                min_words=10,
            )

            assert len(result) == 1
            score, status, _, _, message = result[0]
            assert score < 5.0
            assert status == "ADD_MORE_TEXT"
            assert "comments/docstrings" in message
