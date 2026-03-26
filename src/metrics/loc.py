import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("repopulse.metrics.loc")

SUPPORTED_EXTENSIONS = {".java", ".py", ".ts"}

# matches lines that are empty, whitespace-only, or just a brace
_SKIP_LINE_RE = re.compile(r"^\s*[{}]?\s*$")

# ── Comment‑detection patterns ───────────────────────────────────────────────
# C‑style languages (Java, TypeScript)
_SINGLE_LINE_COMMENT_RE = re.compile(r"^\s*//")          # pure single-line comment
_INLINE_COMMENT_RE = re.compile(r".+//")                  # code + trailing comment
_ML_OPEN_RE = re.compile(r"/\*")                          # /* or /**
_ML_CLOSE_RE = re.compile(r"\*/")
_PURE_ML_LINE_RE = re.compile(r"^\s*(/\*\*?|\*/?|\*/)\s*$")  # lines that are only comment delimiters / continuation

# Python
_PY_SINGLE_COMMENT_RE = re.compile(r"^\s*#")             # pure # comment
_PY_INLINE_COMMENT_RE = re.compile(r".+#")                # code + trailing #


# ── Weighting constants ──────────────────────────────────────────────────────
CODE_WEIGHT = 1.0
COMMENT_WEIGHT = 0.5


@dataclass
class FileLOC:
    path: str
    total_lines: int = 0
    loc: int = 0
    blank_lines: int = 0
    excluded_lines: int = 0
    comment_lines: int = 0
    weighted_loc: float = 0.0


@dataclass
class PackageLOC:
    package: str
    loc: int = 0
    file_count: int = 0
    comment_lines: int = 0
    weighted_loc: float = 0.0
    files: list[FileLOC] = field(default_factory=list)


@dataclass
class ModuleLOC:
    module: str
    loc: int = 0
    package_count: int = 0
    file_count: int = 0
    comment_lines: int = 0
    packages: list[PackageLOC] = field(default_factory=list)


@dataclass
class ProjectLOC:
    project_root: str = ""
    total_loc: int = 0
    total_files: int = 0
    total_blank_lines: int = 0
    total_excluded_lines: int = 0
    total_comment_lines: int = 0
    total_weighted_loc: float = 0.0
    packages: list[PackageLOC] = field(default_factory=list)
    modules: list[ModuleLOC] = field(default_factory=list)
    files: list[FileLOC] = field(default_factory=list)


def calculate_weighted_loc(code_lines: int, comment_lines: int) -> float:
    """Compute weighted LOC: code counts as 1.0, comments as 0.5.

    The rationale is that comment lines still represent meaningful
    developer effort (documentation, explanation) but carry less
    executable complexity than code lines.  The 0.5 weight provides
    a balanced metric that accounts for both.

    Formula:  weighted_loc = (code_lines × 1.0) + (comment_lines × 0.5)
    """
    return (code_lines * CODE_WEIGHT) + (comment_lines * COMMENT_WEIGHT)


def is_supported_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename)
    return ext.lower() in SUPPORTED_EXTENSIONS


def _should_skip_line(line: str) -> tuple[bool, str]:
    stripped = line.rstrip("\n\r")
    if stripped == "" or stripped.isspace():
        return True, "blank"
    if _SKIP_LINE_RE.match(stripped):
        return True, "excluded"
    return False, "code"


def _detect_language(filepath: str) -> str:
    """Return a language hint based on file extension."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".py":
        return "python"
    return "c-style"  # Java & TypeScript share C-style comments


def _classify_line_c_style(stripped: str, in_block: bool) -> tuple[str, bool]:
    """Classify a single line for Java / TypeScript.

    Returns ``(kind, still_in_block)`` where *kind* is one of
    ``"comment"``, ``"mixed"``, ``"code"``, ``"blank"``, or ``"excluded"``.
    """
    # ── inside a block comment ────────────────────────────────────────
    if in_block:
        if _ML_CLOSE_RE.search(stripped):
            # closing */ found – anything after */ is code
            after_close = stripped[stripped.index("*/") + 2:].strip()
            if after_close and not _SKIP_LINE_RE.match(after_close):
                return "mixed", False
            return "comment", False
        return "comment", True

    # ── not currently inside a block comment ──────────────────────────
    # pure single‑line comment  //...
    if _SINGLE_LINE_COMMENT_RE.match(stripped):
        return "comment", False

    # block comment opens on this line  /* or /**
    if _ML_OPEN_RE.search(stripped):
        before_open = stripped[:stripped.index("/*")].strip()
        has_code_before = bool(before_open) and not _SKIP_LINE_RE.match(before_open)

        if _ML_CLOSE_RE.search(stripped[stripped.index("/*") + 2:]):
            # block opens AND closes on the same line
            after_close = stripped[stripped.index("*/") + 2:].strip()
            has_code_after = bool(after_close) and not _SKIP_LINE_RE.match(after_close)
            if has_code_before or has_code_after:
                return "mixed", False
            return "comment", False

        # block opens but does NOT close on this line
        if has_code_before:
            return "mixed", True
        return "comment", True

    # inline trailing comment   code // ...
    if _INLINE_COMMENT_RE.search(stripped):
        return "mixed", False

    return "code", False


def _classify_line_python(stripped: str, in_docstring: bool, docstring_quote: str) -> tuple[str, bool, str]:
    """Classify a single line for Python.

    Returns ``(kind, still_in_docstring, quote_char)`` where *kind* is one of
    ``"comment"``, ``"mixed"``, ``"code"``, ``"blank"``, or ``"excluded"``.
    """
    # ── inside a docstring ────────────────────────────────────────────
    if in_docstring:
        if docstring_quote in stripped:
            # closing quotes found
            after_close = stripped[stripped.index(docstring_quote) + 3:].strip()
            if after_close and not _SKIP_LINE_RE.match(after_close):
                return "mixed", False, ""
            return "comment", False, ""
        return "comment", True, docstring_quote

    # ── not in docstring ──────────────────────────────────────────────
    # pure # comment
    if _PY_SINGLE_COMMENT_RE.match(stripped):
        return "comment", False, ""

    # detect docstring opening (""" or ''')
    for quote in ('"""', "'''"):
        if quote in stripped:
            idx = stripped.index(quote)
            before = stripped[:idx].strip()
            rest = stripped[idx + 3:]

            # check if docstring opens and closes on same line
            if quote in rest:
                close_idx = rest.index(quote)
                after = rest[close_idx + 3:].strip()
                has_code_before = bool(before) and not _SKIP_LINE_RE.match(before)
                has_code_after = bool(after) and not _SKIP_LINE_RE.match(after)
                if has_code_before or has_code_after:
                    return "mixed", False, ""
                return "comment", False, ""

            # opens but does not close
            has_code_before = bool(before) and not _SKIP_LINE_RE.match(before)
            if has_code_before:
                return "mixed", True, quote
            return "comment", True, quote

    # inline trailing # comment
    if _PY_INLINE_COMMENT_RE.search(stripped):
        # Make sure the # isn't inside a string literal (simple heuristic)
        code_part = stripped
        # Strip string literals to avoid false positive
        code_part = re.sub(r'(["\'])(?:(?!\1).)*\1', '', code_part)
        if '#' in code_part:
            return "mixed", False, ""

    return "code", False, ""


def count_loc_in_content(content: str, language: str = "c-style") -> FileLOC:
    result = FileLOC(path="")
    lines = content.split("\n")

    if lines and lines[-1] == "":
        lines = lines[:-1]

    result.total_lines = len(lines)

    in_block = False          # C‑style block comment state
    in_docstring = False      # Python docstring state
    docstring_quote = ""      # which quote style opened the docstring

    for line in lines:
        skip, reason = _should_skip_line(line)
        stripped = line.strip()

        if skip:
            if reason == "blank":
                result.blank_lines += 1
            else:
                result.excluded_lines += 1
            continue

        # ── classify the non‑blank / non‑excluded line ────────────────
        if language == "python":
            kind, in_docstring, docstring_quote = _classify_line_python(
                stripped, in_docstring, docstring_quote
            )
        else:
            kind, in_block = _classify_line_c_style(stripped, in_block)

        if kind == "comment":
            result.comment_lines += 1
        elif kind == "mixed":
            # mixed lines (code + comment) count as LOC; they are not
            # pure comment lines, so comment_lines is NOT incremented.
            result.loc += 1
        else:
            result.loc += 1

    result.weighted_loc = calculate_weighted_loc(result.loc, result.comment_lines)
    return result


def count_loc_in_file(filepath: str, project_root: str = "") -> Optional[FileLOC]:
    if not is_supported_file(filepath):
        return None

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        logger.warning(f"Cannot read file {filepath}: {e}")
        return None

    language = _detect_language(filepath)
    result = count_loc_in_content(content, language=language)
    result.path = os.path.relpath(filepath, project_root) if project_root else filepath
    return result


SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".venv", "build", "dist"}


def count_loc_in_directory(directory: str) -> ProjectLOC:
    project = ProjectLOC(project_root=directory)
    package_map: dict[str, PackageLOC] = {}
    module_map: dict[str, ModuleLOC] = {}

    for dirpath, dirnames, filenames in os.walk(directory):
        logger.debug(f"Scanning directory: {dirpath}")
        rel_dir = os.path.relpath(dirpath, directory)
        parts = rel_dir.split(os.sep)

        # Skip hidden directories (.git, etc.) and known non-source dirs
        if any((p.startswith(".") and p != ".") or p in SKIP_DIRS for p in parts):
            logger.debug(f"Skipped directory: {dirpath}")
            dirnames.clear()  # prevent os.walk from recursing further
            continue

        for filename in sorted(filenames):
            full_path = os.path.join(dirpath, filename)
            if not is_supported_file(filename):
                logger.debug(f"Skipped unsupported file: {full_path}")
                continue

            file_loc = count_loc_in_file(full_path, project_root=directory)
            if file_loc is None:
                logger.debug(f"Skipped unreadable file: {full_path}")
                continue

            logger.debug(f"Counted: {full_path} ({file_loc.loc} LOC)")
            project.files.append(file_loc)
            project.total_loc += file_loc.loc
            project.total_files += 1
            project.total_blank_lines += file_loc.blank_lines
            project.total_excluded_lines += file_loc.excluded_lines
            project.total_comment_lines += file_loc.comment_lines
            project.total_weighted_loc += file_loc.weighted_loc

            pkg_key = rel_dir if rel_dir != "." else "(root)"
            if pkg_key not in package_map:
                package_map[pkg_key] = PackageLOC(package=pkg_key)
            package_map[pkg_key].loc += file_loc.loc
            package_map[pkg_key].file_count += 1
            package_map[pkg_key].comment_lines += file_loc.comment_lines
            package_map[pkg_key].weighted_loc += file_loc.weighted_loc
            package_map[pkg_key].files.append(file_loc)

            # Module is the top-level directory under the project root
            if rel_dir == ".":
                module_key = "(root)"
            else:
                parts = rel_dir.split(os.sep)
                module_key = parts[0] if parts else "(root)"

            if module_key not in module_map:
                module_map[module_key] = ModuleLOC(module=module_key)
            module_map[module_key].loc += file_loc.loc
            module_map[module_key].file_count += 1
            module_map[module_key].comment_lines += file_loc.comment_lines

    project.packages = sorted(package_map.values(), key=lambda p: p.package)
    # Add each package to its module and finish the module list
    pkg_to_module: dict[str, str] = {}
    for pkg in project.packages:
        # e.g. 'src/com/example' -> module is 'src'
        if pkg.package == "(root)":
            mod = "(root)"
        else:
            mod = pkg.package.split(os.sep)[0]
        pkg_to_module[pkg.package] = mod

    for pkg in project.packages:
        mod = pkg_to_module.get(pkg.package, "(root)")
        if mod in module_map:
            module_map[mod].packages.append(pkg)

    project.modules = sorted(module_map.values(), key=lambda m: m.module)

    logger.info(
        f"LOC analysis: {project.total_files} files, "
        f"{project.total_loc} LOC, {project.total_comment_lines} comment lines "
        f"in {len(project.packages)} packages"
    )

    return project
