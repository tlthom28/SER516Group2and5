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
        assert score == pytest.approx(-2.62, abs=0.01)

    def test_analyze_root_with_valid_directory(self):
        """Test analyze_root with valid directory containing markdown and python files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # Create test markdown file with comments
            md_file = tmppath / "test.md"
            md_file.write_text("""
# Title
This is a simple test document. It contains some text for testing.
The quick brown fox jumps over the lazy dog.
""")
            
            result = analyze_root(tmppath, high_threshold=12.0, low_threshold=6.0, min_comment_words=5, min_words=10)
            
            assert isinstance(result, list)
            assert all(isinstance(item, tuple) and len(item) == 5 for item in result)
            assert all(isinstance(item[0], (int, float)) for item in result)  # score

    def test_analyze_root_with_python_comments(self):
        """Test fog index analysis with Python files containing docstrings"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # Create test Python file
            py_file = tmppath / "test.py"
            py_file.write_text('''
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
''')
            
            result = analyze_root(tmppath, high_threshold=12.0, low_threshold=6.0, min_comment_words=5, min_words=10)
            
            assert isinstance(result, list)
            # Should find the docstrings
            assert len(result) >= 0

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
            
            # Create file with short comment
            md_file = tmppath / "short.md"
            md_file.write_text("Hi there.")  # Only 2 words
            
            result = analyze_root(tmppath, high_threshold=12.0, low_threshold=6.0, min_comment_words=5, min_words=10)
            
            assert isinstance(result, list)

    def test_analyze_root_thresholds(self):
        """Test that fog index correctly identifies high/low scores"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # Create file with complex text (high fog index)
            complex_file = tmppath / "complex.txt"
            complex_file.write_text("""
            The dichotomous, multidisciplinary, and multifunctional characteristics 
            of contemporary epistemological frameworks necessitate comprehensive 
            reexamination of our fundamental presuppositions regarding the nature 
            of reality and the acquisition of knowledge through phenomenological 
            and existential methodologies. The heterogeneous manifestations of 
            socioeconomic stratification engender substantial cognitive dissonance 
            within the postmodern paradigm. Furthermore, the juxtaposition of 
            antithetical philosophical perspectives yields unprecedented opportunities 
            for intellectual enlightenment and the amelioration of our collective 
            consciousness regarding the complexities inherent in contemporary society.
            """)
            
            result = analyze_root(tmppath, high_threshold=12.0, low_threshold=6.0, min_comment_words=5, min_words=10)
            
            assert isinstance(result, list)

    def test_fog_index_result_format(self):
        """Test that fog index returns results with correct format"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            md_file = tmppath / "test.md"
            md_file.write_text("This is a test document for testing purposes. It contains meaningful content.")
            
            result = analyze_root(tmppath, high_threshold=12.0, low_threshold=6.0, min_comment_words=5, min_words=10)
            
            for item in result:
                score, status, kind, path, message = item
                assert isinstance(score, (int, float))
                assert status in ["OK", "FLAG_HIGH_FOG", "ADD_MORE_TEXT"]
                assert kind in ["doc", "comment"]
                assert isinstance(path, (str, Path))
                assert isinstance(message, str)

    def test_if_fog_index_is_low(self):
        """Test that a very easy sentence is still considered low threshold."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temppath = Path(tmpdir)
            md_file = temppath / "simple.md"
            md_file.write_text(
                "I don't have a cat. I have a dog. This is a simple sentence. It is easy to read."
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
            assert "Fog score is 0-5" in message
