"""
Test suite for method_coverage service
Tests JavaDoc coverage analysis for methods by visibility
"""
import tempfile
from pathlib import Path
from src.services.method_coverage import scan_repo


class TestMethodCoverageService:
    """Test method comment coverage analysis"""

    def test_scan_repo_with_documented_methods(self):
        """Test scan_repo with properly documented methods"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # Create Java file with documented methods
            java_file = tmppath / "DocumentedClass.java"
            java_file.write_text('''
public class DocumentedClass {
    
    /**
     * Public method with documentation.
     */
    public void publicMethod() {
    }
    
    /**
     * Protected method with documentation.
     */
    protected void protectedMethod() {
    }
    
    /**
     * Private method with documentation.
     */
    private void privateMethod() {
    }
    
    void packageMethod() {
    }
}
''')
            
            result = scan_repo(tmppath)
            
            assert isinstance(result, dict)
            assert "public" in result
            assert "protected" in result
            assert "private" in result
            assert "default" in result
            
            for visibility in result.values():
                assert "coverage" in visibility
                assert "documented" in visibility
                assert "total" in visibility

    def test_scan_repo_calculates_coverage_by_visibility(self):
        """Test that coverage is correctly calculated per visibility level"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            java_file = tmppath / "VisibilityTest.java"
            java_file.write_text('''
public class VisibilityTest {
    
    /** Doc */
    public void publicDoc() {}
    
    public void publicNoDoc() {}
    
    /** Doc */
    private void privateDoc() {}
}
''')
            
            result = scan_repo(tmppath)
            
            # Public: 1 documented, 1 not = 50%
            assert result["public"]["coverage"] == 50.0
            # Private: 1 documented, 0 more = 100%
            assert result["private"]["coverage"] == 100.0

    def test_scan_repo_returns_correct_structure(self):
        """Test that scan_repo returns expected data structure"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            java_file = tmppath / "Test.java"
            java_file.write_text('public class Test { public void method() {} }')
            
            result = scan_repo(tmppath)
            
            assert all(key in result for key in ["public", "protected", "private", "default", "all"])
            
            for visibility, data in result.items():
                assert "coverage" in data
                assert "documented" in data
                assert "total" in data
                assert "threshold" in data
                assert "below_threshold" in data
                assert isinstance(data["coverage"], (int, float, type(None)))
                assert isinstance(data["below_threshold"], int)

    def test_scan_repo_with_no_methods(self):
        """Test scan_repo with file containing no methods"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            java_file = tmppath / "NoMethods.java"
            java_file.write_text('public class NoMethods {}')
            
            result = scan_repo(tmppath)
            
            assert isinstance(result, dict)
            # All coverage should be None or 0
            for visibility in result.values():
                assert visibility["total"] == 0 or visibility["coverage"] is None

    def test_scan_repo_empty_directory(self):
        """Test scan_repo with empty directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            result = scan_repo(tmppath)
            
            assert isinstance(result, dict)
            for visibility in result.values():
                assert visibility["total"] == 0

    def test_scan_repo_identifies_threshold_violations(self):
        """Test that below_threshold flag is set correctly"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # Public methods have 95% threshold
            # Let's create only 1 documented and 1 undocumented = 50% coverage
            java_file = tmppath / "ThresholdTest.java"
            java_file.write_text('''
public class ThresholdTest {
    /** Doc */
    public void method1() {}
    
    public void method2() {}
}
''')
            
            result = scan_repo(tmppath)
            
            # Public coverage is 50%, threshold is 95%, so should be below threshold
            assert result["public"]["below_threshold"] == 1

    def test_scan_repo_multiple_files(self):
        """Test scan_repo with multiple Java files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            
            # Create multiple files with proper formatting
            file1 = tmppath / "File1.java"
            file1.write_text('''
public class File1 { 
    /** Doc */ 
    public void method1() {
    }
}
''')
            
            file2 = tmppath / "File2.java"
            file2.write_text('''
public class File2 { 
    public void method2() {
    }
}
''')
            
            result = scan_repo(tmppath)
            
            # Should have found methods across files
            assert result["public"]["total"] >= 2
