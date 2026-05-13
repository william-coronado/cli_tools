"""Raw git output fixtures for parser tests.

Log fixtures use \x00 as record separator and \x1f as field separator,
matching LOG_FORMAT in LogParser.
"""
from __future__ import annotations

# ── git log fixtures ───────────────────────────────────────────────────────────

def _log_record(
    hash_: str,
    short: str,
    name: str,
    email: str,
    date: str,
    subject: str,
    body: str = "",
    files: list[str] | None = None,
    insertions: int = 0,
    deletions: int = 0,
) -> str:
    files = files or []
    n = len(files)
    files_block = "\n".join(files)
    if insertions and deletions:
        stat = f" {n} file{'s' if n != 1 else ''} changed, {insertions} insertions(+), {deletions} deletions(-)"
    elif insertions:
        stat = f" {n} file{'s' if n != 1 else ''} changed, {insertions} insertions(+)"
    elif deletions:
        stat = f" {n} file{'s' if n != 1 else ''} changed, {deletions} deletions(-)"
    else:
        stat = f" {n} file{'s' if n != 1 else ''} changed"

    tail = f"{body}\n\n{files_block}\n\n{stat}\n"
    return f"\x00{hash_}\x1f{short}\x1f{name}\x1f{email}\x1f{date}\x1f{subject}\x1f{tail}"


LOG_SIMPLE = (
    _log_record(
        hash_="aaaa111122223333444455556666777788880000",
        short="aaaa1111",
        name="Will C",
        email="will@example.com",
        date="2026-05-12T10:00:00+00:00",
        subject="feat: add classifier",
        files=["src/classifier.py"],
        insertions=50,
    )
    + _log_record(
        hash_="bbbb111122223333444455556666777788880000",
        short="bbbb1111",
        name="Will C",
        email="will@example.com",
        date="2026-05-09T10:00:00+00:00",
        subject="fix: handle edge case",
        files=["src/classifier.py", "tests/test_classifier.py"],
        insertions=10,
        deletions=3,
    )
    + _log_record(
        hash_="cccc111122223333444455556666777788880000",
        short="cccc1111",
        name="Jane D",
        email="jane@example.com",
        date="2026-05-01T10:00:00+00:00",
        subject="docs: update README",
        files=["README.md"],
        insertions=5,
    )
)

LOG_WITH_BODY = _log_record(
    hash_="dddd111122223333444455556666777788880000",
    short="dddd1111",
    name="Will C",
    email="will@example.com",
    date="2026-05-10T12:00:00+00:00",
    subject="refactor: extract helpers",
    body="This is a multi-line body.\n\nWith a second paragraph.",
    files=["src/utils.py"],
    insertions=20,
    deletions=5,
)

# ── git diff fixtures ──────────────────────────────────────────────────────────

DIFF_MODIFIED = """\
diff --git a/src/classifier.py b/src/classifier.py
index abc1234..def5678 100644
--- a/src/classifier.py
+++ b/src/classifier.py
@@ -10,7 +10,10 @@ class Classifier:
     def fit(self, X, y):
-        self.threshold_ = 0.5
+        if self.tune:
+            self.threshold_ = self._tune(X, y)
+        else:
+            self.threshold_ = 0.5
         return self
@@ -30,4 +33,3 @@ class Classifier:
     def predict(self, X):
-        # TODO: remove
         return X @ self.weights_
"""

DIFF_RENAMED = """\
diff --git a/old_name.py b/new_name.py
similarity index 85%
rename from old_name.py
rename to new_name.py
index abc1234..def5678 100644
--- a/old_name.py
+++ b/new_name.py
@@ -1,3 +1,3 @@
 def foo():
-    return 1
+    return 2
"""

DIFF_BINARY = """\
diff --git a/assets/logo.png b/assets/logo.png
index abc1234..def5678 100644
Binary files a/assets/logo.png and b/assets/logo.png differ
"""

# ── git blame --porcelain fixtures ────────────────────────────────────────────

BLAME_PORCELAIN = """\
aaaa111122223333444455556666777788880000 1 1 10
author Will C
author-mail <will@example.com>
author-time 1747043200
author-tz +0000
committer Will C
committer-mail <will@example.com>
committer-time 1747043200
committer-tz +0000
summary feat: add classifier
filename src/classifier.py
\tclass Classifier:
aaaa111122223333444455556666777788880000 2 2
\t    def __init__(self):
bbbb111122223333444455556666777788880000 3 3 8
author Jane D
author-mail <jane@example.com>
author-time 1746000000
author-tz +0000
committer Jane D
committer-mail <jane@example.com>
committer-time 1746000000
committer-tz +0000
summary fix: handle edge case
filename src/classifier.py
\t        self.threshold_ = 0.5
bbbb111122223333444455556666777788880000 4 4
\t        self.weights_ = None
bbbb111122223333444455556666777788880000 5 5
\t
bbbb111122223333444455556666777788880000 6 6
\t    def fit(self, X, y):
bbbb111122223333444455556666777788880000 7 7
\t        self.threshold_ = 0.5
bbbb111122223333444455556666777788880000 8 8
\t        return self
bbbb111122223333444455556666777788880000 9 9
\t
bbbb111122223333444455556666777788880000 10 10
\t    def predict(self, X):
"""

# ── git status --porcelain=v2 --branch fixtures ───────────────────────────────

STATUS_CLEAN = """\
# branch.oid aaaa111122223333444455556666777788880000
# branch.head main
# branch.upstream origin/main
# branch.ab +0 -0
"""

STATUS_STAGED = """\
# branch.oid aaaa111122223333444455556666777788880000
# branch.head feature/foo
# branch.upstream origin/feature/foo
# branch.ab +2 -0
1 M. N... 100644 100644 100644 abc def src/classifier.py
1 A. N... 000000 100644 100644 000 abc tests/test_new.py
1 .M N... 100644 100644 100644 abc abc src/utils.py
? scratch.py
"""

STATUS_AHEAD = """\
# branch.oid aaaa111122223333444455556666777788880000
# branch.head feature/bar
# branch.upstream origin/feature/bar
# branch.ab +3 -1
1 M. N... 100644 100644 100644 abc def src/main.py
"""
