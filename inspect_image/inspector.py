from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class MissingOptionalDep(RuntimeError):
    """Raised when Pillow isn't installed."""


class WrongContentType(RuntimeError):
    """Raised when the file isn't a readable image."""


@dataclass
class ImageInfo:
    path: str
    width: int
    height: int
    mode: str
    format: str | None
    file_size_bytes: int

    def to_markdown(self) -> str:
        from .renderer import render_markdown
        return render_markdown(self)

    def to_json(self) -> dict:
        from .renderer import render_json
        return render_json(self)

    def to_text(self) -> str:
        from .renderer import render_text
        return render_text(self)


def inspect_image(path: str | Path) -> ImageInfo:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as e:
        raise MissingOptionalDep(
            "Pillow is required for inspect_image. Install with: pip install Pillow"
        ) from e

    try:
        with Image.open(p) as im:
            width, height = im.size
            mode = im.mode
            fmt = im.format
    except UnidentifiedImageError as e:
        raise WrongContentType(f"Not a recognized image format: {p}") from e
    except OSError as e:
        raise WrongContentType(f"Could not read image: {e}") from e

    return ImageInfo(
        path=str(p),
        width=width,
        height=height,
        mode=mode,
        format=fmt,
        file_size_bytes=p.stat().st_size,
    )
