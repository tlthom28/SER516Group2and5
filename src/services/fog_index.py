"""
Fog Index scanner for code comments.
Measures readability of code comments using Flesch-Kincaid readability metric.
"""
import logging
import re
import tokenize
import io
import ast
from pathlib import Path
from collections import Counter

CODE_FILE = {".py", ".java"}
BLOCK_COMMENT_CODE_FILE = {".java"}
IGNORE_DIRECTORY = {
    ".git", "build", "target", ".gradle", ".idea",
    ".vscode", "__pycache__", ".pytest_cache", ".DS_Store",
    "Dockerfile", ".gitignore", ".gitkeep", ".yml", ".yaml"
}
LINE_PREFIXES = {".py": ["#"], ".java": ["//"]}
WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
SENTENCE_SPLIT_RE = re.compile(r"[.!?]+|\n{2,}|\n(?=\s*[-*+]\s)|\n(?=\s*\d+\.\s)")
SUPPORTED_FILE_EXTENSIONS = CODE_FILE
logger = logging.getLogger("repopulse.services.fog_index")


def iterate_files(root: Path):
    """Scan for code files to compute the fog index."""
    for path in root.rglob("*"):
        if (path.is_file() and path.suffix.lower() in SUPPORTED_FILE_EXTENSIONS and not any(part in IGNORE_DIRECTORY for part in path.parts)):
            yield path


def extract_text(path: Path):
    """Extract text for fog index scan from a file, returning the text and its comments."""
    extracted_text = path.suffix.lower()
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        logger.warning(
            "Failed to read file for fog index...",
            path.as_posix(),
        )
        return None, None

    if extracted_text in CODE_FILE:
        if extracted_text == ".py":
            return extract_python_comments(raw), "comment"
        return extract_generic_comments(raw, extracted_text), "comment"
    return None, None


def extract_python_comments(text: str) -> str:
    """Extract comments and docstrings from Python code."""
    out = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                out.append(token.string.lstrip("# ").strip())
    except tokenize.TokenError:
        pass

    try:
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                docstring = ast.get_docstring(node, clean=True)
                if docstring:
                    out.append(docstring)
    except SyntaxError:
        pass
    return "\n".join(out)


def extract_generic_comments(text: str, extracted_text: str) -> str:
    """Extract comments from code files that support line and block comments."""
    out = []

    if extracted_text in BLOCK_COMMENT_CODE_FILE:
        for block in re.findall(r"/\*.*?\*/", text, flags=re.S):
            block = re.sub(r"^/\*+|\*+/$", "", block).strip()
            block = re.sub(r"^\s*\*\s?", "", block, flags=re.M)
            out.append(block)

    for line in text.splitlines():
        stripped = line.lstrip()
        for prefix in LINE_PREFIXES.get(extracted_text, []):
            if stripped.startswith(prefix):
                out.append(stripped[len(prefix):].strip())
                break

    return "\n".join(out)


def fog_index(text: str, kind: str = "doc"):
    """Compute the fog index (Flesch-Kincaid) for a given text."""
    words_list = words(text)
    sentences_list = sentences(text, kind)
    if not words_list or not sentences_list:
        return None
    syllables = sum(syllable_count(word) for word in words_list)
    return (0.39 * (len(words_list) / len(sentences_list)) + 11.8 * (syllables / len(words_list)) - 15.59)


def words(text: str):
    """Extract words from text."""
    return WORD_RE.findall(text)


def sentences(text: str, kind: str = "doc"):
    """Split text into sentences based on punctuation."""
    if kind == "comment":
        return [line for line in text.splitlines() if WORD_RE.search(line)]
    return [sentence for sentence in SENTENCE_SPLIT_RE.split(text) if WORD_RE.search(sentence)]


def syllable_count(word: str) -> int:
    """Count syllables in a word."""
    word_chars = re.sub(r"[^a-z]", "", word.lower())
    if not word_chars:
        return 0
    groups = re.findall(r"[aeiouy]+", word_chars)
    count = len(groups)
    if word_chars.endswith("e"):
        count -= 1
    if word_chars.endswith("le") and len(word_chars) > 2 and word_chars[-3] not in "aeiouy":
        count += 1
    return max(1, count)


def analyze_file(path: Path, high_threshold: float, low_threshold: float, min_comment_words: int, min_words: int):
    """Analyze a single file and return fog index score with status."""
    ext = path.suffix.lower()
    if ext not in SUPPORTED_FILE_EXTENSIONS:
        label = ext if ext else "[no extension]"
        return (None, "UNSUPPORTED", "other", path, f"Unsupported file type.")

    text, kind = extract_text(path)
    if text is None:
        return (None, "READ_ERROR", "other", path, "Could not read file text.")

    words_count = len(words(text))
    if words_count == 0:
        return (None, "NO_COMMENTS", kind, path, "No comment text found.")

    if kind == "comment" and words_count < min_comment_words:
        return (None, "ADD_MORE_TEXT", kind, path, f"Only {words_count} comment words.")

    if words_count < min_words:
        return (None, "ADD_MORE_TEXT", kind, path, f"Only {words_count} words.")

    score = fog_index(text, kind)
    if score is None:
        return (None, "ADD_MORE_TEXT", kind, path, "Not enough sentences.")

    if score <= low_threshold:
        status = "ADD_MORE_TEXT"
        message = "Fog score is 0-5. Please add more meaningful comments/docstrings."
    elif score > high_threshold:
        status = "FLAG_HIGH_FOG"
        message = "Hard to read. Simplify your comments/docstrings."
    else:
        status = "OK"
        message = ""

    return (score, status, kind, path, message)


def analyze_root(root: Path, high_threshold: float, low_threshold: float, min_comment_words: int, min_words: int):
    """Analyze all files in root directory and return sorted results."""
    root = Path(root)
    logger.info(
        "Starting fog index analysis: root=%s high_threshold=%.2f low_threshold=%.2f min_comment_words=%d min_words=%d",
        root.as_posix(),
        high_threshold,
        low_threshold,
        min_comment_words,
        min_words,
    )

    paths = list(iterate_files(root))
    logger.info(
        "Discovered files for fog index: root=%s supported_files=%d",
        root.as_posix(),
        len(paths),
    )

    rows = []
    status_counts = Counter()
    scored_files = 0

    for path in paths:
        row = analyze_file(path, high_threshold, low_threshold, min_comment_words, min_words)
        rows.append(row)

        score, status, kind, result_path, message = row
        if score is not None:
            scored_files += 1
        status_counts[status] += 1

        try:
            display_path = Path(result_path).relative_to(root).as_posix()
        except ValueError:
            display_path = Path(result_path).as_posix()

        logger.info(
            "Fog index file summary: file=%s status=%s kind=%s score=%s",
            display_path,
            status,
            kind,
            "n/a" if score is None else f"{score:.2f}",
        )

        if message:
            logger.info(
                "Fog index file detail: file=%s message=%s",
                display_path,
                message,
            )

    rows.sort(key=lambda row: (row[0] is None, -(row[0] or 0), str(row[3])))
    logger.info(
        "Fog index analysis complete: root=%s files=%d scored=%d ok=%d high_fog=%d add_more_text=%d no_comments=%d read_errors=%d unsupported=%d",
        root.as_posix(),
        len(rows),
        scored_files,
        status_counts["OK"],
        status_counts["FLAG_HIGH_FOG"],
        status_counts["ADD_MORE_TEXT"],
        status_counts["NO_COMMENTS"],
        status_counts["READ_ERROR"],
        status_counts["UNSUPPORTED"],
    )
    return rows
