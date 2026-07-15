from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .inspector import ImageInfo


def render_markdown(info: "ImageInfo") -> str:
    lines = [
        f"# Image: {info.path}",
        "",
        f"- **Dimensions**: {info.width} x {info.height}",
        f"- **Mode**: {info.mode}",
        f"- **Format**: {info.format or 'unknown'}",
        f"- **File size**: {info.file_size_bytes:,} bytes",
    ]
    return "\n".join(lines)


def render_json(info: "ImageInfo") -> dict:
    return {
        "path": info.path,
        "width": info.width,
        "height": info.height,
        "mode": info.mode,
        "format": info.format,
        "file_size_bytes": info.file_size_bytes,
    }


def render_text(info: "ImageInfo") -> str:
    return (
        f"{info.path}: {info.width}x{info.height} {info.mode} "
        f"{info.format or 'unknown'} ({info.file_size_bytes:,} bytes)"
    )
