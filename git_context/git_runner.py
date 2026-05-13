from __future__ import annotations
import subprocess  # used only by GitRunner.run internals
from pathlib import Path


class GitError(Exception):
    def __init__(self, message: str, command: list[str], returncode: int):
        self.command = command
        self.returncode = returncode
        super().__init__(message)


class NotAGitRepoError(GitError): ...
class FileNotTrackedError(GitError): ...
class GitBinaryNotFoundError(Exception): ...


class GitRunner:
    def __init__(
        self,
        repo_path: Path,
        timeout_seconds: float = 30.0,
        git_binary: str = "git",
    ):
        self.repo_path = repo_path
        self.timeout = timeout_seconds
        self.git_binary = git_binary
        self._repo_root: Path | None = None

    def run(self, *args: str, check: bool = True) -> str:
        cmd = [self.git_binary, *args]
        try:
            result = subprocess.run(
                cmd,
                cwd=self.repo_path,
                capture_output=True,
                timeout=self.timeout,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            raise GitBinaryNotFoundError(
                f"git binary not found: {self.git_binary!r}"
            )
        except subprocess.TimeoutExpired:
            raise GitError(
                f"git command timed out after {self.timeout}s: {' '.join(cmd)}",
                command=cmd,
                returncode=-1,
            )
        if check and result.returncode != 0:
            raise GitError(
                f"git command failed (exit {result.returncode}): {' '.join(cmd)}\n"
                f"stderr: {result.stderr.strip()}",
                command=cmd,
                returncode=result.returncode,
            )
        return result.stdout

    def run_lines(self, *args: str) -> list[str]:
        return [line for line in self.run(*args).splitlines() if line]

    def get_repo_root(self) -> Path:
        if self._repo_root is not None:
            return self._repo_root
        try:
            raw = self.run("rev-parse", "--show-toplevel").strip()
        except GitError as e:
            raise NotAGitRepoError(
                "Not inside a git repository",
                command=e.command,
                returncode=e.returncode,
            )
        self._repo_root = Path(raw)
        return self._repo_root

    def get_default_branch(self) -> str:
        # 1. Try symbolic-ref of origin/HEAD
        ref = self.run("symbolic-ref", "refs/remotes/origin/HEAD", check=False).strip()
        if ref:
            return ref.split("/")[-1]

        # 2. Does "main" exist?
        if self.run("rev-parse", "--verify", "main", check=False).strip():
            return "main"

        # 3. Does "master" exist?
        if self.run("rev-parse", "--verify", "master", check=False).strip():
            return "master"

        # 4. Fall back to current branch
        return self.run("rev-parse", "--abbrev-ref", "HEAD").strip()

    def file_exists_in_git(self, file_path: str) -> bool:
        result = self.run("ls-files", "--error-unmatch", file_path, check=False)
        return bool(result.strip())
