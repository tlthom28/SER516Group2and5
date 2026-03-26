import os
import tempfile
import shutil

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.metrics.loc import (
    count_loc_in_content,
    count_loc_in_file,
    count_loc_in_directory,
    is_supported_file,
    calculate_weighted_loc,
)

client = TestClient(app)
SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "sample_files")


def _sample_path(*parts):
    return os.path.join(SAMPLE_DIR, *parts)


class TestJavaFileLOC:

    def test_calculator_java_loc(self):
        result = count_loc_in_file(
            _sample_path("java_project", "src", "com", "example", "Calculator.java")
        )
        assert result is not None
        assert result.total_lines > 0
        assert result.loc > 0
        assert result.blank_lines > 0
        assert result.excluded_lines > 0
        assert result.comment_lines == 0
        assert result.loc < result.total_lines
        assert result.loc + result.blank_lines + result.excluded_lines + result.comment_lines == result.total_lines

    def test_main_java_loc(self):
        result = count_loc_in_file(
            _sample_path("java_project", "src", "com", "example", "Main.java")
        )
        assert result is not None
        assert result.total_lines == 11
        assert result.loc + result.blank_lines + result.excluded_lines + result.comment_lines == result.total_lines

    def test_stringhelper_java_loc(self):
        result = count_loc_in_file(
            _sample_path("java_project", "src", "com", "example", "util", "StringHelper.java")
        )
        assert result is not None
        assert result.loc > 0
        assert result.loc + result.blank_lines + result.excluded_lines + result.comment_lines == result.total_lines


class TestPythonFileLOC:

    def test_calculator_py_loc(self):
        result = count_loc_in_file(_sample_path("python_project", "calculator.py"))
        assert result is not None
        assert result.total_lines > 0
        assert result.loc > 0
        assert result.blank_lines >= 1
        assert result.comment_lines == 2  # two docstring lines
        assert result.loc + result.blank_lines + result.excluded_lines + result.comment_lines == result.total_lines

    def test_main_py_loc(self):
        result = count_loc_in_file(_sample_path("python_project", "main.py"))
        assert result is not None
        assert result.loc > 0
        assert result.comment_lines == 1  # one docstring line
        assert result.loc + result.blank_lines + result.excluded_lines + result.comment_lines == result.total_lines


class TestTypeScriptFileLOC:

    def test_calculator_ts_loc(self):
        result = count_loc_in_file(_sample_path("ts_project", "src", "calculator.ts"))
        assert result is not None
        assert result.total_lines == 24
        assert result.loc > 0
        assert result.excluded_lines > 0
        assert result.comment_lines == 0
        assert result.loc + result.blank_lines + result.excluded_lines + result.comment_lines == result.total_lines

    def test_index_ts_loc(self):
        result = count_loc_in_file(_sample_path("ts_project", "src", "index.ts"))
        assert result is not None
        assert result.loc > 0
        assert result.loc + result.blank_lines + result.excluded_lines + result.comment_lines == result.total_lines


class TestCountLOCInContent:

    def test_empty_content(self):
        result = count_loc_in_content("")
        assert result.total_lines == 0
        assert result.loc == 0

    def test_only_blank_lines(self):
        result = count_loc_in_content("\n\n\n")
        assert result.loc == 0
        assert result.blank_lines == 3

    def test_only_braces(self):
        content = "{\n}\n  {  \n  }  \n"
        result = count_loc_in_content(content)
        assert result.loc == 0
        assert result.excluded_lines == 4

    def test_mixed_content(self):
        content = (
            "package com.example;\n"
            "\n"
            "public class Foo {\n"
            "\n"
            "    int x = 1;\n"
            "    \n"
            "}\n"
        )
        result = count_loc_in_content(content)
        assert result.loc == 3
        assert result.blank_lines == 3
        assert result.excluded_lines == 1
        assert result.total_lines == 7

    def test_whitespace_only_lines(self):
        content = "  \n\t\n   \t   \n"
        result = count_loc_in_content(content)
        assert result.loc == 0
        assert result.blank_lines == 3


class TestCommentDetection:
    """Tests for comment classification across all supported comment types."""

    # ── 1. Single‑line comments  // ──────────────────────────────────────

    def test_single_line_comment_java(self):
        content = (
            "package com.example;\n"
            "// This is a single-line comment\n"
            "public class Foo {\n"
            "}\n"
        )
        result = count_loc_in_content(content, language="c-style")
        assert result.comment_lines == 1
        assert result.loc == 2          # package + class declaration
        assert result.excluded_lines == 1  # closing brace
        assert result.loc + result.blank_lines + result.excluded_lines + result.comment_lines == result.total_lines

    # ── 2. Multi‑line comments  /* … */ ──────────────────────────────────

    def test_multiline_comment_block(self):
        content = (
            "int x = 1;\n"
            "/* this is\n"
            "   a multi-line\n"
            "   comment */\n"
            "int y = 2;\n"
        )
        result = count_loc_in_content(content, language="c-style")
        assert result.comment_lines == 3  # 3 lines of block comment
        assert result.loc == 2            # x and y declarations

    # ── 3. Javadoc comments  /** … */ ────────────────────────────────────

    def test_javadoc_comment(self):
        content = (
            "/**\n"
            " * Adds two numbers.\n"
            " * @param a first operand\n"
            " * @param b second operand\n"
            " * @return sum of a and b\n"
            " */\n"
            "public int add(int a, int b) {\n"
            "    return a + b;\n"
            "}\n"
        )
        result = count_loc_in_content(content, language="c-style")
        assert result.comment_lines == 6  # all 6 Javadoc lines
        assert result.loc == 2            # method signature + return
        assert result.excluded_lines == 1  # closing brace

    # ── 4. Mixed line (code + trailing comment) ──────────────────────────

    def test_mixed_code_and_comment(self):
        content = (
            "int x = 1; // initialise x\n"
            "int y = 2;\n"
        )
        result = count_loc_in_content(content, language="c-style")
        # mixed line counts as LOC, not as a pure comment
        assert result.loc == 2
        assert result.comment_lines == 0

    # ── 5. Python # single‑line comment ──────────────────────────────────

    def test_python_hash_comment(self):
        content = (
            "# This is a comment\n"
            "x = 1\n"
            "# Another comment\n"
            "y = 2\n"
        )
        result = count_loc_in_content(content, language="python")
        assert result.comment_lines == 2
        assert result.loc == 2

    # ── 6. Python docstrings ─────────────────────────────────────────────

    def test_python_docstring_single_line(self):
        content = (
            '"""Module docstring."""\n'
            "x = 1\n"
        )
        result = count_loc_in_content(content, language="python")
        assert result.comment_lines == 1
        assert result.loc == 1

    def test_python_docstring_multiline(self):
        content = (
            '"""\n'
            "This is a\n"
            "multi-line docstring.\n"
            '"""\n'
            "x = 1\n"
        )
        result = count_loc_in_content(content, language="python")
        assert result.comment_lines == 4  # all 4 docstring lines
        assert result.loc == 1

    # ── 7. Inline comment on same line as code – C‑style ─────────────────

    def test_inline_block_comment_same_line(self):
        content = "int x = /* default */ 5;\n"
        result = count_loc_in_content(content, language="c-style")
        # entire line treated as mixed → LOC
        assert result.loc == 1
        assert result.comment_lines == 0

    # ── 8. Consecutive single‑line comments ──────────────────────────────

    def test_consecutive_single_line_comments(self):
        content = (
            "// comment 1\n"
            "// comment 2\n"
            "// comment 3\n"
            "int x = 1;\n"
        )
        result = count_loc_in_content(content, language="c-style")
        assert result.comment_lines == 3
        assert result.loc == 1

    # ── 9. Mixed Python line (code + # comment) ─────────────────────────

    def test_python_inline_comment(self):
        content = "x = 1  # set x\n"
        result = count_loc_in_content(content, language="python")
        assert result.loc == 1
        assert result.comment_lines == 0  # mixed → counts as LOC

    # ── 10. No comments at all ───────────────────────────────────────────

    def test_no_comments(self):
        content = (
            "int a = 1;\n"
            "int b = 2;\n"
            "int c = a + b;\n"
        )
        result = count_loc_in_content(content, language="c-style")
        assert result.comment_lines == 0
        assert result.loc == 3

    # ── 11. Invariant holds for all comment scenarios ────────────────────

    def test_invariant_with_comments(self):
        content = (
            "package com.example;\n"
            "\n"
            "// utility class\n"
            "/**\n"
            " * Does stuff.\n"
            " */\n"
            "public class Bar {\n"
            "    int x = 1; // init\n"
            "\n"
            "}\n"
        )
        result = count_loc_in_content(content, language="c-style")
        assert result.loc + result.blank_lines + result.excluded_lines + result.comment_lines == result.total_lines


class TestWeightedLOC:
    """Tests for the weighted LOC calculation: code × 1.0 + comments × 0.5."""

    # ── 1. Pure code – no comments → weighted == raw LOC ─────────────────

    def test_pure_code_weighted_equals_raw(self):
        content = (
            "int a = 1;\n"
            "int b = 2;\n"
            "int c = a + b;\n"
        )
        result = count_loc_in_content(content, language="c-style")
        assert result.loc == 3
        assert result.comment_lines == 0
        assert result.weighted_loc == 3.0  # 3×1.0 + 0×0.5

    # ── 2. Pure comments – no code → weighted == comments × 0.5 ──────────

    def test_pure_comments_weighted(self):
        content = (
            "// comment one\n"
            "// comment two\n"
            "// comment three\n"
            "// comment four\n"
        )
        result = count_loc_in_content(content, language="c-style")
        assert result.loc == 0
        assert result.comment_lines == 4
        assert result.weighted_loc == 2.0  # 0×1.0 + 4×0.5

    # ── 3. Mixed code and comments → correct weighting ───────────────────

    def test_code_and_comments_weighted(self):
        content = (
            "package com.example;\n"
            "// utility class\n"
            "public class Foo {\n"
            "    int x = 1;\n"
            "}\n"
        )
        result = count_loc_in_content(content, language="c-style")
        # code: package, class decl, int x = 3 LOC; comment: 1; excluded: } = 1
        assert result.loc == 3
        assert result.comment_lines == 1
        assert result.weighted_loc == 3.5  # 3×1.0 + 1×0.5

    # ── 4. Empty file → weighted == 0.0 ──────────────────────────────────

    def test_empty_content_weighted_zero(self):
        result = count_loc_in_content("")
        assert result.weighted_loc == 0.0

    # ── 5. Javadoc block – many comment lines ────────────────────────────

    def test_javadoc_weighted(self):
        content = (
            "/**\n"
            " * Adds two numbers.\n"
            " * @param a first\n"
            " * @param b second\n"
            " */\n"
            "public int add(int a, int b) {\n"
            "    return a + b;\n"
            "}\n"
        )
        result = count_loc_in_content(content, language="c-style")
        assert result.loc == 2
        assert result.comment_lines == 5
        assert result.weighted_loc == 4.5  # 2×1.0 + 5×0.5

    # ── 6. Python docstrings – weighted correctly ────────────────────────

    def test_python_docstring_weighted(self):
        content = (
            '"""Module docstring."""\n'
            "\n"
            "def foo():\n"
            '    """Function docstring."""\n'
            "    return 1\n"
        )
        result = count_loc_in_content(content, language="python")
        assert result.comment_lines == 2  # two docstring lines
        assert result.loc == 2            # def + return
        assert result.weighted_loc == 3.0  # 2×1.0 + 2×0.5

    # ── 7. calculate_weighted_loc function directly ──────────────────────

    def test_calculate_weighted_loc_direct(self):
        assert calculate_weighted_loc(10, 0) == 10.0
        assert calculate_weighted_loc(0, 10) == 5.0
        assert calculate_weighted_loc(10, 10) == 15.0
        assert calculate_weighted_loc(0, 0) == 0.0
        assert calculate_weighted_loc(100, 20) == 110.0

    # ── 8. Mixed line (code+comment) counts as code weight only ──────────

    def test_mixed_line_weighted_as_code(self):
        content = (
            "int x = 1; // init\n"
            "int y = 2;\n"
        )
        result = count_loc_in_content(content, language="c-style")
        # mixed line → loc=2, comment_lines=0
        assert result.loc == 2
        assert result.comment_lines == 0
        assert result.weighted_loc == 2.0  # 2×1.0 + 0×0.5

    # ── 9. Directory-level weighted LOC sums correctly ────────────────────

    def test_directory_weighted_loc_sums(self):
        project = count_loc_in_directory(_sample_path("python_project"))
        assert project.total_weighted_loc > 0
        assert project.total_weighted_loc == pytest.approx(
            sum(f.weighted_loc for f in project.files)
        )
        # weighted < raw LOC + comments because comments are halved
        assert project.total_weighted_loc <= project.total_loc + project.total_comment_lines

    # ── 10. API response includes weighted_loc ───────────────────────────

    def test_endpoint_returns_weighted_loc(self):
        abs_path = os.path.abspath(_sample_path("java_project"))
        response = client.post("/metrics/loc", json={"repo_path": abs_path})
        assert response.status_code == 200
        data = response.json()
        assert "total_weighted_loc" in data
        assert data["total_weighted_loc"] >= 0
        for f in data["files"]:
            assert "weighted_loc" in f
        for pkg in data["packages"]:
            assert "weighted_loc" in pkg


class TestDirectoryScanning:

    def test_java_project_packages(self):
        project = count_loc_in_directory(_sample_path("java_project"))
        assert project.total_files == 3
        assert project.total_loc > 0
        assert len(project.packages) == 2

        pkg_names = {p.package for p in project.packages}
        assert any("example" in p and "util" not in p for p in pkg_names)
        assert any("util" in p for p in pkg_names)

    def test_python_project_scope(self):
        project = count_loc_in_directory(_sample_path("python_project"))
        assert project.total_files == 2
        assert project.total_loc > 0
        assert len(project.packages) == 1

    def test_ts_project_scope(self):
        project = count_loc_in_directory(_sample_path("ts_project"))
        assert project.total_files == 2
        assert project.total_loc > 0
        assert len(project.packages) == 1

    def test_project_totals_equal_sum_of_files(self):
        project = count_loc_in_directory(_sample_path("java_project"))
        assert project.total_loc == sum(f.loc for f in project.files)
        assert project.total_comment_lines == sum(f.comment_lines for f in project.files)

    def test_project_totals_equal_sum_of_packages(self):
        project = count_loc_in_directory(_sample_path("java_project"))
        assert project.total_loc == sum(p.loc for p in project.packages)
        assert project.total_comment_lines == sum(p.comment_lines for p in project.packages)

    def test_java_project_modules(self):
        project = count_loc_in_directory(_sample_path("java_project"))
        assert len(project.modules) == 1
        assert project.total_loc == sum(m.loc for m in project.modules)
        assert project.total_loc == sum(f.loc for f in project.files)

    def test_python_project_has_comment_lines(self):
        project = count_loc_in_directory(_sample_path("python_project"))
        assert project.total_comment_lines > 0  # docstrings present
        assert project.total_comment_lines == sum(f.comment_lines for f in project.files)


class TestEdgeCases:

    def test_unsupported_extension_ignored(self):
        assert is_supported_file("readme.md") is False
        assert is_supported_file("data.json") is False
        assert is_supported_file("Makefile") is False

    def test_supported_extensions(self):
        assert is_supported_file("App.java") is True
        assert is_supported_file("main.py") is True
        assert is_supported_file("index.ts") is True

    def test_count_loc_returns_none_for_unsupported(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
            f.write("Hello world\n")
            tmp_path = f.name
        try:
            assert count_loc_in_file(tmp_path) is None
        finally:
            os.unlink(tmp_path)

    def test_empty_directory(self):
        tmp_dir = tempfile.mkdtemp()
        try:
            project = count_loc_in_directory(tmp_dir)
            assert project.total_loc == 0
            assert project.total_files == 0
            assert len(project.packages) == 0
        finally:
            shutil.rmtree(tmp_dir)


class TestLOCEndpoint:

    def test_loc_endpoint_with_java_project(self):
        abs_path = os.path.abspath(_sample_path("java_project"))
        response = client.post("/metrics/loc", json={"repo_path": abs_path})
        assert response.status_code == 200
        data = response.json()
        assert data["total_files"] == 3
        assert data["total_loc"] > 0
        assert "total_comment_lines" in data
        assert data["total_comment_lines"] >= 0
        assert len(data["packages"]) == 2
        assert len(data["files"]) == 3
        # every file response must include comment_lines
        for f in data["files"]:
            assert "comment_lines" in f

    def test_loc_endpoint_includes_modules(self):
        abs_path = os.path.abspath(_sample_path("java_project"))
        response = client.post("/metrics/loc", json={"repo_path": abs_path})
        assert response.status_code == 200
        data = response.json()
        assert "modules" in data
        assert isinstance(data["modules"], list)
        assert len(data["modules"]) >= 1
        for m in data["modules"]:
            assert "module" in m
            assert "loc" in m
            assert "packages" in m

    def test_loc_endpoint_invalid_path(self):
        response = client.post("/metrics/loc", json={"repo_path": "/nonexistent/path/to/repo"})
        assert response.status_code == 404

    def test_loc_endpoint_missing_field(self):
        response = client.post("/metrics/loc", json={})
        assert response.status_code == 400 or response.status_code == 422

    def test_loc_endpoint_relative_path_rejected(self):
        response = client.post("/metrics/loc", json={"repo_path": "relative/path"})
        assert response.status_code == 400 or response.status_code == 422
