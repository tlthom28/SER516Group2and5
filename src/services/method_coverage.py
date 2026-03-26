"""
Method Comment Coverage analyzer for Java code.
Measures the percentage of Java methods with JavaDoc comments by visibility level.
"""
import re
from pathlib import Path

CODE_FILE = {".java"}
IGNORE_DIRECTORY = {".git", "target", "build", ".idea", ".gradle"}

METHOD_THRESHOLDS = {
    "public": 95.0,
    "protected": 80.0,
    "private": 60.0,
    "default": 80.0,
    "all": 80.0,
}

JAVA_METHOD_RE = re.compile(
    r"""^\s*
    (?:(?:public|protected|private|static|final|abstract|synchronized|native|default|strictfp)\s+)*
    (?:<[^>]+>\s+)?
    (?:[\w\[\]<>?,.@]+\s+)?
    ([A-Za-z_]\w*)\s*
    \([^;{}]*\)\s*
    (?:throws[^{;]+)?\s*
    (?:\{|;)
    """,
    re.X,
)

VIS_RE = re.compile(r"\b(public|protected|private)\b")
CONTROL_WORDS = {"if", "for", "while", "switch", "catch", "return", "new", "do", "try"}


def iterate_java_files(root: Path):
    """Yield Java files under root, skipping ignored directories."""
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in CODE_FILE:
            if not any(part in IGNORE_DIRECTORY for part in path.parts):
                yield path


def visibility(signature: str) -> str:
    """Extract visibility level from method signature, defaulting to package-private."""
    m = VIS_RE.search(signature)
    return m.group(1) if m else "default"


def extract_java_methods(text: str):
    """Parse Java source text and return methods with visibility and JavaDoc status."""
    methods = []
    lines = text.splitlines()
    i = 0
    pending_javadoc = False
    signature_buffer = []

    while i < len(lines):
        stripped = lines[i].strip()

        # Mark next method as documented when a JavaDoc block appears
        if stripped.startswith("/**"):
            while i < len(lines) and "*/" not in lines[i]:
                i += 1
            pending_javadoc = True
            i += 1
            continue

        # Regular block comments do not count as method documentation
        if stripped.startswith("/*") and not stripped.startswith("/**"):
            while i < len(lines) and "*/" not in lines[i]:
                i += 1
            pending_javadoc = False
            signature_buffer = []
            i += 1
            continue

        if stripped.startswith("//"):
            pending_javadoc = False
            signature_buffer = []
            i += 1
            continue

        if not stripped:
            i += 1
            continue

        if stripped.startswith("@"):
            signature_buffer.append(stripped)
            i += 1
            continue

        # Buffer multi-line signatures
        signature_buffer.append(stripped)
        joined = " ".join(signature_buffer)

        m = JAVA_METHOD_RE.match(joined)
        if m:
            name = m.group(1)
            if name not in CONTROL_WORDS:
                methods.append({
                    "name": name,
                    "visibility": visibility(joined),
                    "documented": pending_javadoc,
                })
            pending_javadoc = False
            signature_buffer = []
        elif "{" in stripped or ";" in stripped:
            pending_javadoc = False
            signature_buffer = []

        i += 1

    return methods


def coverage(methods):
    """Compute documented count, total count, and percent coverage."""
    total = len(methods)
    if total == 0:
        return None, 0, 0
    documented = sum(1 for m in methods if m["documented"])
    return (100.0 * documented / total), documented, total


def scan_repo(repo_root: Path):
    """Scan a repository and aggregate method comment coverage by visibility."""
    grouped = {
        "all": {"documented": 0, "total": 0},
        "public": {"documented": 0, "total": 0},
        "protected": {"documented": 0, "total": 0},
        "private": {"documented": 0, "total": 0},
        "default": {"documented": 0, "total": 0},
    }

    for path in iterate_java_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        methods = extract_java_methods(text)
        _, doc_all, total_all = coverage(methods)
        grouped["all"]["documented"] += doc_all
        grouped["all"]["total"] += total_all

        by_vis = {"public": [], "protected": [], "private": [], "default": []}
        for m in methods:
            by_vis[m["visibility"]].append(m)

        for vis, vis_methods in by_vis.items():
            _, doc, total = coverage(vis_methods)
            grouped[vis]["documented"] += doc
            grouped[vis]["total"] += total

    out = {}
    for vis, counts in grouped.items():
        total = counts["total"]
        documented = counts["documented"]
        cov = (100.0 * documented / total) if total else None
        threshold = METHOD_THRESHOLDS[vis]
        out[vis] = {
            "coverage": cov,
            "documented": documented,
            "total": total,
            "threshold": threshold,
            "below_threshold": 1 if (cov is not None and cov < threshold) else 0,
        }

    return out
