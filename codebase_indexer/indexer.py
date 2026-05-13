from __future__ import annotations
import concurrent.futures
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_tools_root = Path(__file__).parent.parent
if str(_tools_root) not in sys.path:
    sys.path.insert(0, str(_tools_root))


@dataclass
class ImportEntry:
    module: str
    names: list[str]
    alias: str | None
    is_relative: bool


@dataclass
class FunctionEntry:
    name: str
    signature: str
    docstring: str | None
    decorators: list[str]
    is_async: bool
    line_number: int
    is_method: bool


@dataclass
class ClassEntry:
    name: str
    bases: list[str]
    docstring: str | None
    decorators: list[str]
    line_number: int
    methods: list[FunctionEntry]


@dataclass
class FileIndex:
    path: str
    language: str
    line_count: int
    size_bytes: int
    imports: list[ImportEntry]
    functions: list[FunctionEntry]
    classes: list[ClassEntry]
    constants: list[str]
    parse_error: str | None


@dataclass
class CodebaseIndex:
    root_path: str
    generated_at: str
    total_files: int
    total_lines: int
    languages: dict[str, int]
    files: list[FileIndex]
    skipped_files: list[str]
    estimated_tokens: int | None

    def to_markdown(self, detail: str = "normal") -> str:
        from .renderer import render_markdown
        return render_markdown(self, detail)

    def to_json(self) -> dict:
        from .renderer import render_json
        return render_json(self)

    def to_outline(self) -> str:
        from .renderer import render_outline
        return render_outline(self)


class CodebaseIndexer:
    def __init__(
        self,
        root: str | Path,
        extra_excludes: list[str] | None = None,
        respect_gitignore: bool = True,
        max_file_size_kb: int = 500,
        include_extensions: list[str] | None = None,
        show_progress: bool = True,
        workers: int | None = None,
    ):
        self._root = Path(root).resolve()
        if not self._root.exists():
            raise FileNotFoundError(f"Root path does not exist: {self._root}")
        if not self._root.is_dir():
            raise ValueError(f"Root path is not a directory: {self._root}")
        self._extra_excludes = extra_excludes
        self._respect_gitignore = respect_gitignore
        self._max_file_size_kb = max_file_size_kb
        self._include_extensions = include_extensions
        self._show_progress = show_progress
        self._workers = workers or min(8, os.cpu_count() or 1)

    def build(self) -> CodebaseIndex:
        from .walker import RepoWalker
        from .parsers.python_parser import PythonParser
        from .parsers.generic_parser import GenericParser

        parsers = [PythonParser(), GenericParser()]

        walker = RepoWalker(
            root=self._root,
            extra_excludes=self._extra_excludes,
            respect_gitignore=self._respect_gitignore,
            max_file_size_kb=self._max_file_size_kb,
            include_extensions=self._include_extensions,
        )
        files_to_parse = list(walker.walk())
        skipped = list(walker.skipped_files)

        if not files_to_parse:
            print("Warning: no files found after applying exclusion rules.", file=sys.stderr)

        def _parse(path: Path) -> FileIndex | None:
            parser = self._select_parser(path, parsers)
            if parser is None:
                return None
            try:
                return parser.parse(path, self._root)
            except Exception as exc:
                rel = str(path.relative_to(self._root))
                return FileIndex(
                    path=rel, language="unknown", line_count=0, size_bytes=0,
                    imports=[], functions=[], classes=[], constants=[],
                    parse_error=f"Unexpected error: {exc}",
                )

        file_indices: list[FileIndex] = []

        _console = None
        if self._show_progress:
            try:
                from rich.console import Console
                _console = Console(stderr=True)
            except ImportError:
                pass

        if _console is not None:
            from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=_console,
            ) as progress:
                task_id = progress.add_task("Indexing...", total=len(files_to_parse))
                with concurrent.futures.ThreadPoolExecutor(max_workers=self._workers) as exe:
                    futures = {exe.submit(_parse, p): p for p in files_to_parse}
                    for fut in concurrent.futures.as_completed(futures):
                        result = fut.result()
                        if result is not None:
                            file_indices.append(result)
                        progress.advance(task_id)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self._workers) as exe:
                results = list(exe.map(_parse, files_to_parse))
            file_indices = [r for r in results if r is not None]

        file_indices.sort(key=lambda f: f.path)

        total_lines = sum(f.line_count for f in file_indices)
        languages: dict[str, int] = {}
        for f in file_indices:
            languages[f.language] = languages.get(f.language, 0) + 1

        return CodebaseIndex(
            root_path=str(self._root),
            generated_at=datetime.now(timezone.utc).isoformat(),
            total_files=len(file_indices),
            total_lines=total_lines,
            languages=languages,
            files=file_indices,
            skipped_files=skipped,
            estimated_tokens=None,
        )

    def _select_parser(self, path: Path, parsers: list) -> object | None:
        for parser in parsers:
            if parser.can_parse(path):
                return parser
        return None
