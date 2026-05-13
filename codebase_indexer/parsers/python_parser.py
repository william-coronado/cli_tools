from __future__ import annotations
import ast
from pathlib import Path

from .base import BaseParser
from ..indexer import ClassEntry, FileIndex, FunctionEntry, ImportEntry

_MAX_DEFAULT_LEN = 20
_MAX_SIG_LEN = 120


class PythonParser(BaseParser):
    def can_parse(self, path: Path) -> bool:
        return path.suffix in (".py", ".pyi")

    def parse(self, path: Path, root: Path) -> FileIndex:
        rel = str(path.relative_to(root))
        try:
            size = path.stat().st_size
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return FileIndex(
                path=rel, language="python", line_count=0, size_bytes=0,
                imports=[], functions=[], classes=[], constants=[],
                parse_error=str(exc),
            )

        line_count = source.count("\n") + (1 if source and not source.endswith("\n") else 0)

        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            return FileIndex(
                path=rel, language="python", line_count=line_count, size_bytes=size,
                imports=[], functions=[], classes=[], constants=[],
                parse_error=f"SyntaxError: {exc}",
            )
        except Exception as exc:
            return FileIndex(
                path=rel, language="python", line_count=line_count, size_bytes=size,
                imports=[], functions=[], classes=[], constants=[],
                parse_error=f"ParseError: {exc}",
            )

        return FileIndex(
            path=rel,
            language="python",
            line_count=line_count,
            size_bytes=size,
            imports=self._extract_imports(tree),
            functions=self._extract_functions(tree),
            classes=self._extract_classes(tree),
            constants=self._extract_constants(tree),
            parse_error=None,
        )

    def _extract_imports(self, tree: ast.Module) -> list[ImportEntry]:
        entries: list[ImportEntry] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    entries.append(ImportEntry(
                        module=alias.name,
                        names=[],
                        alias=alias.asname,
                        is_relative=False,
                    ))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    module = "." * node.level + module
                names = [a.name for a in node.names]
                entries.append(ImportEntry(
                    module=module,
                    names=names,
                    alias=None,
                    is_relative=node.level > 0,
                ))
        return entries

    def _extract_functions(self, tree: ast.Module) -> list[FunctionEntry]:
        funcs: list[FunctionEntry] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append(self._make_function_entry(node, is_method=False))
        return funcs

    def _extract_classes(self, tree: ast.Module) -> list[ClassEntry]:
        classes: list[ClassEntry] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    self._make_function_entry(item, is_method=True)
                    for item in ast.iter_child_nodes(node)
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                classes.append(ClassEntry(
                    name=node.name,
                    bases=[ast.unparse(b) for b in node.bases],
                    docstring=self._get_docstring(node),
                    decorators=self._get_decorators(node),
                    line_number=node.lineno,
                    methods=methods,
                ))
        return classes

    def _extract_constants(self, tree: ast.Module) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper() and target.id not in seen:
                        seen.add(target.id)
                        names.append(target.id)
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id.isupper() and node.target.id not in seen:
                    seen.add(node.target.id)
                    names.append(node.target.id)
        return names

    def _make_function_entry(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_method: bool
    ) -> FunctionEntry:
        return FunctionEntry(
            name=node.name,
            signature=self._build_signature(node),
            docstring=self._get_docstring(node),
            decorators=self._get_decorators(node),
            is_async=isinstance(node, ast.AsyncFunctionDef),
            line_number=node.lineno,
            is_method=is_method,
        )

    def _build_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        args = node.args
        parts: list[str] = []

        # defaults cover the last N of (posonlyargs + args)
        all_pos = args.posonlyargs + args.args
        n_defaults = len(args.defaults)
        defaults_start = len(all_pos) - n_defaults

        def _dflt(idx: int) -> str:
            if idx >= defaults_start:
                raw = ast.unparse(args.defaults[idx - defaults_start])
                return "=" + (raw[:_MAX_DEFAULT_LEN] + "..." if len(raw) > _MAX_DEFAULT_LEN else raw)
            return ""

        for i, arg in enumerate(args.posonlyargs):
            s = arg.arg
            if arg.annotation:
                s += f": {ast.unparse(arg.annotation)}"
            s += _dflt(i)
            parts.append(s)
        if args.posonlyargs:
            parts.append("/")

        for i, arg in enumerate(args.args):
            s = arg.arg
            if arg.annotation:
                s += f": {ast.unparse(arg.annotation)}"
            s += _dflt(len(args.posonlyargs) + i)
            parts.append(s)

        if args.vararg:
            s = f"*{args.vararg.arg}"
            if args.vararg.annotation:
                s += f": {ast.unparse(args.vararg.annotation)}"
            parts.append(s)
        elif args.kwonlyargs:
            parts.append("*")

        for i, arg in enumerate(args.kwonlyargs):
            s = arg.arg
            if arg.annotation:
                s += f": {ast.unparse(arg.annotation)}"
            if args.kw_defaults[i] is not None:
                raw = ast.unparse(args.kw_defaults[i])
                s += "=" + (raw[:_MAX_DEFAULT_LEN] + "..." if len(raw) > _MAX_DEFAULT_LEN else raw)
            parts.append(s)

        if args.kwarg:
            s = f"**{args.kwarg.arg}"
            if args.kwarg.annotation:
                s += f": {ast.unparse(args.kwarg.annotation)}"
            parts.append(s)

        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        arg_str = ", ".join(parts)
        sig = f"{prefix} {node.name}({arg_str}){ret}"

        if len(sig) > _MAX_SIG_LEN:
            sig = f"{prefix} {node.name}(...){ret}"
        return sig

    def _get_docstring(self, node: ast.AST) -> str | None:
        raw = ast.get_docstring(node, clean=True)
        return raw if raw else None

    def _get_decorators(self, node: ast.AST) -> list[str]:
        return [f"@{ast.unparse(d)}" for d in getattr(node, "decorator_list", [])]
