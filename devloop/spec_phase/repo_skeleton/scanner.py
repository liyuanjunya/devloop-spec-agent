"""tree-sitter based repository scanner.

Extracts file-level symbols (classes, functions, methods) from a repo
across multiple languages. Used by RepoSkeletonBuilder to build a
project map.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# Language detection by extension
EXT_TO_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}

# Per-language tree-sitter node types we extract as symbols
SYMBOL_NODES = {
    "python": {
        "class_definition": "class",
        "function_definition": "function",
    },
    "javascript": {
        "class_declaration": "class",
        "function_declaration": "function",
        "method_definition": "method",
    },
    "typescript": {
        "class_declaration": "class",
        "function_declaration": "function",
        "method_definition": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "type",
    },
    "rust": {
        "function_item": "function",
        "struct_item": "struct",
        "enum_item": "enum",
        "trait_item": "trait",
    },
    "java": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "method_declaration": "method",
    },
}


@dataclass
class Symbol:
    """A code symbol extracted from a source file."""

    name: str
    kind: str  # class | function | method | interface | ...
    line: int
    end_line: int
    path: str
    parent: str | None = None  # parent class name for methods, etc.


@dataclass
class FileScan:
    path: str
    language: str
    line_count: int
    symbols: list[Symbol] = field(default_factory=list)


def detect_language(path: Path) -> str | None:
    return EXT_TO_LANG.get(path.suffix.lower())


def _load_parsers() -> dict[str, object]:
    """Lazy-load tree-sitter parsers for supported languages.

    Tries `tree_sitter_language_pack` (current) then `tree_sitter_languages` (legacy).
    """
    parsers: dict[str, object] = {}
    get_parser = None
    try:
        from tree_sitter_language_pack import get_parser as gp  # type: ignore

        get_parser = gp
    except ImportError:
        try:
            from tree_sitter_languages import get_parser as gp  # type: ignore

            get_parser = gp
        except ImportError:
            logger.warning(
                "No tree-sitter language pack installed; falling back to filename-only scan"
            )
            return parsers

    for lang in SYMBOL_NODES.keys():
        try:
            parser = get_parser(lang)
            parsers[lang] = parser
        except Exception as e:
            logger.debug("Could not load tree-sitter parser for %s: %s", lang, e)
    return parsers


_PARSERS_LOCAL = threading.local()


def get_parsers() -> dict[str, object]:
    """Per-thread parser cache. tree-sitter Parser objects are NOT thread-safe."""
    parsers = getattr(_PARSERS_LOCAL, "parsers", None)
    if parsers is None:
        parsers = _load_parsers()
        _PARSERS_LOCAL.parsers = parsers
    return parsers


def _extract_symbols_treesitter(
    source: bytes, language: str, parser, path: str
) -> list[Symbol]:
    """Walk the AST and pull out symbols of interest."""
    tree = parser.parse(source)
    root = tree.root_node
    targets = SYMBOL_NODES.get(language, {})
    symbols: list[Symbol] = []

    def walk(node, parent_name: str | None = None) -> None:
        nt = node.type
        if nt in targets:
            name = _node_name(node)
            if name:
                symbols.append(
                    Symbol(
                        name=name,
                        kind=targets[nt],
                        line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        path=path,
                        parent=parent_name,
                    )
                )
                # Recurse into class body to pick up methods with this parent
                if targets[nt] in ("class", "interface"):
                    for child in node.children:
                        walk(child, parent_name=name)
                    return
        for child in node.children:
            walk(child, parent_name=parent_name)

    walk(root)
    return symbols


def _node_name(node) -> str | None:
    """Best-effort name extraction from a definition node."""
    for child in node.children:
        if child.type in ("identifier", "type_identifier", "property_identifier"):
            try:
                return child.text.decode("utf-8", errors="replace")
            except Exception:
                return None
        # Some grammars wrap the name
        if child.type == "name":
            for sub in child.children:
                if sub.type in ("identifier", "type_identifier"):
                    try:
                        return sub.text.decode("utf-8", errors="replace")
                    except Exception:
                        return None
    # Fallback: scan all descendants for first identifier
    for descendant in _iter_children(node, depth=2):
        if descendant.type in ("identifier", "type_identifier"):
            try:
                return descendant.text.decode("utf-8", errors="replace")
            except Exception:
                return None
    return None


def _iter_children(node, depth: int = 2):
    if depth == 0:
        return
    for child in node.children:
        yield child
        yield from _iter_children(child, depth - 1)


def scan_file(path: Path, repo_root: Path) -> FileScan | None:
    """Scan a single source file. Returns None for unsupported / binary files."""
    lang = detect_language(path)
    if lang is None:
        return None
    try:
        source = path.read_bytes()
    except (OSError, UnicodeDecodeError):
        return None
    # Skip tiny or huge files
    if len(source) == 0:
        return None
    if len(source) > 2 * 1024 * 1024:  # 2 MB
        return None

    rel_path = str(path.relative_to(repo_root))
    line_count = source.count(b"\n") + 1

    parsers = get_parsers()
    parser = parsers.get(lang)
    if parser is None:
        # Fallback: no symbols extracted but we still note the file
        return FileScan(path=rel_path, language=lang, line_count=line_count, symbols=[])

    try:
        symbols = _extract_symbols_treesitter(source, lang, parser, rel_path)
    except Exception as e:
        logger.debug("tree-sitter parse failed for %s: %s", path, e)
        symbols = []

    return FileScan(path=rel_path, language=lang, line_count=line_count, symbols=symbols)


def _walk_files(root: Path, excluded_dirs: set[str]):
    """Walk source files. Skips symlinks and excluded directories to avoid loops."""
    seen: set[str] = set()
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    # Skip symlinks entirely to avoid cycles
                    continue
                if entry.is_dir():
                    if entry.name in excluded_dirs:
                        continue
                    # Loop protection by resolved path
                    try:
                        resolved = str(entry.resolve(strict=False))
                    except (OSError, RuntimeError):
                        continue
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    stack.append(entry)
                elif entry.is_file():
                    yield entry
            except OSError:
                continue


def scan_repo(
    repo_root: Path,
    *,
    excluded_dirs: set[str],
    supported_languages: set[str],
    max_files: int = 5000,
) -> list[FileScan]:
    """Walk the repo and scan supported source files."""
    repo_root = repo_root.resolve()
    out: list[FileScan] = []
    count = 0

    for f in _walk_files(repo_root, excluded_dirs):
        if count >= max_files:
            logger.warning("scan_repo: hit max_files=%d cap", max_files)
            break
        lang = detect_language(f)
        if lang is None or lang not in supported_languages:
            continue
        scan = scan_file(f, repo_root)
        if scan is not None:
            out.append(scan)
            count += 1

    return out
