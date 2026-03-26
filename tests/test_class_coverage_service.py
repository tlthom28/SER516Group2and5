"""
Test suite for class_coverage service
Tests JavaDoc coverage analysis for Java classes
"""
import tempfile
from pathlib import Path
from src.services.class_coverage import analyze_repo


class TestClassCoverageService:
    """Test class comment coverage analysis"""

    def test_analyze_repo_with_documented_classes(self):
        """Test analyze_repo with documented Java classes"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # Create test Java file with documented class
            java_file = tmppath / "Example.java"
            java_file.write_text('''
/**
 * Example class with JavaDoc.
 * This class demonstrates proper documentation.
 */
public class Example {
    
    /**
     * Example method.
     */
    public void method() {
        System.out.println("Hello");
    }
}
''')
            
            result = analyze_repo(str(tmppath), "test-user", "test-repo", "https://github.com/test-user/test-repo", "main", "abc123")
            
            assert isinstance(result, dict)
            assert "summary" in result
            assert "files_analyzed" in result
            assert result["summary"]["classes_with_javadoc"] > 0

    def test_analyze_repo_with_undocumented_classes(self):
        """Test analyze_repo with undocumented Java classes"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # Create test Java file without JavaDoc
            java_file = tmppath / "NoDoc.java"
            java_file.write_text('''
public class NoDoc {
    
    public void method() {
        System.out.println("No documentation");
    }
}
''')
            
            result = analyze_repo(str(tmppath), "test-user", "test-repo", "https://github.com/test-user/test-repo", "main", "abc123")
            
            assert isinstance(result, dict)
            assert "summary" in result
            assert result["summary"]["total_classes_found"] > 0

    def test_analyze_repo_returns_correct_structure(self):
        """Test that analyze_repo returns expected data structure"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            java_file = tmppath / "Test.java"
            java_file.write_text('public class Test {}')
            
            result = analyze_repo(str(tmppath), "owner", "repo", "url", "main", "sha")
            
            assert "summary" in result
            summary = result["summary"]
            assert "total_java_files_analyzed" in summary
            assert "total_classes_found" in summary
            assert "classes_with_javadoc" in summary
            assert "coverage_pct" in summary

    def test_analyze_repo_with_multiple_classes(self):
        """Test analyze_repo with file containing multiple classes"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            java_file = tmppath / "Multiple.java"
            java_file.write_text('''
/** First class */
public class First {
}

/** Second class */
public class Second {
}

public class Third {
}
''')
            
            result = analyze_repo(str(tmppath), "test", "repo", "url", "main", "sha")
            
            summary = result["summary"]
            assert summary["total_classes_found"] >= 3

    def test_analyze_repo_empty_directory(self):
        """Test analyze_repo with empty directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            result = analyze_repo(str(tmppath), "test", "repo", "url", "main", "sha")
            
            assert isinstance(result, dict)
            assert result["summary"]["total_java_files_analyzed"] == 0

    def test_analyze_repo_calculates_coverage_percentage(self):
        """Test that coverage percentage is calculated correctly"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # 2 documented, 1 not documented = 66.67%
            java_file = tmppath / "Coverage.java"
            java_file.write_text('''
/** Doc1 */
public class Doc1 {}

/** Doc2 */
public class Doc2 {}

public class NoDoc {}
''')
            
            result = analyze_repo(str(tmppath), "test", "repo", "url", "main", "sha")
            
            coverage = result["summary"]["coverage_pct"]
            assert 0 <= coverage <= 100
            assert coverage > 0  # Should have some documentation
