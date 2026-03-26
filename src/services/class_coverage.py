"""
Class Comment Coverage analyzer for Java code.
Measures the percentage of Java classes with JavaDoc comments.
"""
import os
import re
from pathlib import Path

EXCLUDED_PATH_FRAGMENTS = ["test", "target", "out", "generated", "build"]
EXCLUDED_FILE_SUFFIXES = ["Test.java", "Tests.java"]

CLASS_DECLARATION = re.compile(
    r"""
    ^\s*
    (?:(?:public|protected|private|abstract|static|final|sealed|non-sealed)\s+)*
    (class|interface|enum|record)
    \s+
    ([A-Za-z_$][A-Za-z0-9_$]*)
    """,
    re.VERBOSE,
)

PACKAGE_DECLARATION = re.compile(r"^\s*package\s+([\w.]+)\s*;")


def _is_excluded(java_file_path: str) -> bool:
    """Check if a Java file should be excluded from analysis."""
    path_lower = java_file_path.replace("\\", "/").lower()
    for fragment in EXCLUDED_PATH_FRAGMENTS:
        if f"/{fragment}/" in path_lower or path_lower.startswith(f"{fragment}/"):
            return True
    for suffix in EXCLUDED_FILE_SUFFIXES:
        if java_file_path.endswith(suffix):
            return True
    return False


def discover_java_files(repo_root: str) -> list:
    """Discover all Java files in the repository."""
    java_files = []
    for dirpath, _dirnames, filenames in os.walk(repo_root):
        for filename in filenames:
            if not filename.endswith(".java"):
                continue
            full_path = os.path.join(dirpath, filename)
            relative_path = os.path.relpath(full_path, repo_root).replace("\\", "/")
            if not _is_excluded(relative_path):
                java_files.append(full_path)
    return java_files


def parse_java_file(file_path: str, repo_root: str) -> dict:
    """Parse a single Java file and extract class information with JavaDoc status."""
    relative_path = os.path.relpath(file_path, repo_root).replace("\\", "/")

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return {"file_path": relative_path, "package": "", "classes": [], "error": "Could not read file"}

    # Extract package name
    package_name = ""
    for line in lines:
        m = PACKAGE_DECLARATION.match(line)
        if m:
            package_name = m.group(1)
            break

    # Build token list (javadoc, block_comment, class)
    tokens = []
    i = 0
    total_lines = len(lines)
    brace_depth = 0

    while i < total_lines:
        line = lines[i]

        # Detect JavaDoc opening /**
        if "/**" in line:
            javadoc_lines = []
            start = i
            while i < total_lines:
                javadoc_lines.append(lines[i].rstrip("\n"))
                if "*/" in lines[i]:
                    break
                i += 1
            raw = "\n".join(javadoc_lines)
            tokens.append(("javadoc", start, i, raw))
            i += 1
            continue

        # Detect regular block comment
        if re.search(r"/\*(?!\*)", line):
            start = i
            while i < total_lines:
                if "*/" in lines[i]:
                    break
                i += 1
            tokens.append(("block_comment", start, i, None))
            i += 1
            continue

        # Detect class-like declaration
        m = CLASS_DECLARATION.search(line)
        if m:
            keyword = m.group(1)
            class_type = "abstract class" if (keyword == "class" and re.search(r"\babstract\b", line)) else keyword
            class_name = m.group(2)
            is_nested = brace_depth > 0

            tokens.append(("class", i, i, {
                "class_name": class_name,
                "class_type": class_type,
                "start_line": i + 1,
                "is_nested": is_nested,
            }))

        # Track brace depth
        in_string = False
        in_char = False
        j = 0
        while j < len(line):
            ch = line[j]
            if ch == '"' and not in_char:
                in_string = not in_string
            elif ch == "'" and not in_string:
                in_char = not in_char
            elif not in_string and not in_char:
                if ch == "{":
                    brace_depth += 1
                elif ch == "}":
                    brace_depth = max(0, brace_depth - 1)
            if ch == "\\" and (in_string or in_char):
                j += 1
            j += 1

        i += 1

    # Match each class to preceding JavaDoc
    classes = []
    for idx, token in enumerate(tokens):
        if token[0] != "class":
            continue

        class_data = token[3]
        class_name = class_data["class_name"]
        fqn = f"{package_name}.{class_name}" if package_name else class_name

        has_javadoc = False
        javadoc_line_count = 0
        javadoc_char_count = 0
        has_author = False
        has_since = False
        has_version = False

        # Look backwards for preceding JavaDoc
        for back in range(idx - 1, -1, -1):
            prev = tokens[back]
            if prev[0] == "javadoc":
                gap = token[1] - prev[2]
                if gap <= 2:
                    raw = prev[3]
                    has_javadoc = True
                    javadoc_line_count = raw.count("\n") + 1
                    javadoc_char_count = len(raw)
                    has_author = "@author" in raw
                    has_since = "@since" in raw
                    has_version = "@version" in raw
                break
            elif prev[0] in ("class", "block_comment"):
                break

        classes.append({
            "class_name": class_name,
            "fully_qualified_name": fqn,
            "class_type": class_data["class_type"],
            "start_line": class_data["start_line"],
            "is_nested": class_data["is_nested"],
            "has_javadoc": has_javadoc,
            "javadoc_line_count": javadoc_line_count,
            "javadoc_char_count": javadoc_char_count,
            "javadoc_has_author": has_author,
            "javadoc_has_since": has_since,
            "javadoc_has_version": has_version,
        })

    return {
        "file_path": relative_path,
        "package": package_name,
        "classes": classes,
    }


def analyze_repo(
    repo_root: str,
    repo_owner: str,
    repo_name: str,
    repo_url: str,
    default_branch: str,
    commit_sha: str = "",
) -> dict:
    """Analyze repository-level class comment coverage."""
    java_files = discover_java_files(repo_root)
    file_results = [parse_java_file(fp, repo_root) for fp in java_files]

    all_classes = [
        {**cls, "file_path": fr["file_path"], "package": fr["package"]}
        for fr in file_results
        for cls in fr["classes"]
    ]

    total_classes = len(all_classes)
    classes_with_javadoc = sum(1 for c in all_classes if c["has_javadoc"])
    coverage_pct = round((classes_with_javadoc / total_classes * 100), 2) if total_classes > 0 else 0.0

    return {
        "repository": {
            "owner": repo_owner,
            "name": repo_name,
            "url": repo_url,
            "default_branch": default_branch,
            "commit_sha": commit_sha,
        },
        "summary": {
            "total_java_files_analyzed": len(java_files),
            "total_classes_found": total_classes,
            "classes_with_javadoc": classes_with_javadoc,
            "classes_without_javadoc": total_classes - classes_with_javadoc,
            "coverage_pct": coverage_pct,
        },
        "files_analyzed": [
            {
                "file_path": fr["file_path"],
                "package": fr["package"],
                "total_classes": len(fr["classes"]),
                "classes_with_javadoc": sum(1 for c in fr["classes"] if c["has_javadoc"]),
                "coverage_pct": round(
                    sum(1 for c in fr["classes"] if c["has_javadoc"]) / len(fr["classes"]) * 100, 2
                ) if fr["classes"] else 0.0,
                "classes": fr["classes"],
            }
            for fr in file_results
        ],
    }
