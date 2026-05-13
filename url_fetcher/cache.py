from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


class DiskCache:
    def __init__(
        self,
        cache_dir: Path | None = None,
        ttl: int = 3600,
    ) -> None:
        self._dir = Path(cache_dir) if cache_dir else Path.home() / ".cache" / "url_fetcher"
        self._dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl

    def get(self, url: str) -> tuple[bytes, dict] | None:
        key = self._cache_key(url)
        content_path = self._dir / f"{key}.html"
        meta_path = self._dir / f"{key}.json"
        if not content_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            age = time.time() - meta.get("cached_at", 0)
            if age > self.ttl:
                return None
            return content_path.read_bytes(), meta
        except Exception:
            return None

    def set(self, url: str, content: bytes, metadata: dict) -> None:
        key = self._cache_key(url)
        meta = {**metadata, "cached_at": time.time()}
        (self._dir / f"{key}.html").write_bytes(content)
        (self._dir / f"{key}.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )

    def delete(self, url: str) -> bool:
        key = self._cache_key(url)
        deleted = False
        for ext in (".html", ".json"):
            p = self._dir / f"{key}{ext}"
            if p.exists():
                p.unlink()
                deleted = True
        return deleted

    def clear(self, older_than_seconds: int | None = None) -> int:
        count = 0
        now = time.time()
        for meta_path in self._dir.glob("*.json"):
            try:
                if older_than_seconds is not None:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    age = now - meta.get("cached_at", 0)
                    if age <= older_than_seconds:
                        continue
                stem = meta_path.stem
                for ext in (".html", ".json"):
                    p = self._dir / f"{stem}{ext}"
                    if p.exists():
                        p.unlink()
                count += 1
            except Exception:
                pass
        return count

    def stats(self) -> dict:
        entries = list(self._dir.glob("*.json"))
        total_size = sum(
            (self._dir / f"{p.stem}.html").stat().st_size
            for p in entries
            if (self._dir / f"{p.stem}.html").exists()
        )
        oldest = 0.0
        now = time.time()
        for p in entries:
            try:
                meta = json.loads(p.read_text(encoding="utf-8"))
                age = now - meta.get("cached_at", now)
                oldest = max(oldest, age)
            except Exception:
                pass
        return {
            "total_entries": len(entries),
            "total_size_bytes": total_size,
            "oldest_entry_age_seconds": int(oldest),
        }

    def _cache_key(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()[:16]
