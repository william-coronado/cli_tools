from __future__ import annotations

import urllib.parse
import urllib.robotparser


class RobotsChecker:
    USER_AGENT = "url-fetcher"

    def __init__(self) -> None:
        self._cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    def is_allowed(self, url: str) -> bool:
        robots_url = self._get_robots_url(url)
        if robots_url not in self._cache:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            try:
                rp.read()
            except Exception:
                # Fail open — don't block on robots.txt errors
                return True
            self._cache[robots_url] = rp
        try:
            return self._cache[robots_url].can_fetch(self.USER_AGENT, url)
        except Exception:
            return True

    def _get_robots_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"
