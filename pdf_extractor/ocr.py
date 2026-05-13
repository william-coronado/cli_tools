from __future__ import annotations
from typing import Protocol, runtime_checkable

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None  # type: ignore[assignment]


@runtime_checkable
class OCRBackend(Protocol):
    def image_to_text(self, image: object) -> tuple[str, float | None]:
        """Return (extracted_text, confidence_or_None)."""
        ...


class PytesseractBackend:
    _CONF_THRESHOLD = 30

    def __init__(self, language: str = "eng") -> None:
        self.language = language

    def image_to_text(self, image: object) -> tuple[str, float | None]:
        try:
            import pytesseract
        except ImportError:
            raise RuntimeError(
                "pytesseract is not installed. Install it with:\n"
                "  pip install pytesseract\n"
                "and ensure Tesseract is installed:\n"
                "  Ubuntu: sudo apt install tesseract-ocr\n"
                "  macOS:  brew install tesseract"
            )

        data = pytesseract.image_to_data(
            image, lang=self.language, output_type=pytesseract.Output.DICT
        )

        words: list[str] = []
        confidences: list[float] = []
        for word, conf in zip(data["text"], data["conf"]):
            try:
                conf_val = float(conf)
            except (ValueError, TypeError):
                continue
            if conf_val >= self._CONF_THRESHOLD and word.strip():
                words.append(word)
                confidences.append(conf_val)

        text = " ".join(words)
        avg_conf = sum(confidences) / len(confidences) if confidences else None
        return text, avg_conf


class EasyOCRBackend:
    def __init__(self, languages: list[str] | None = None) -> None:
        self.languages = languages or ["en"]
        self._reader = None

    def _get_reader(self) -> object:
        if self._reader is None:
            try:
                import easyocr  # type: ignore[import]
            except ImportError:
                raise RuntimeError(
                    "easyocr is not installed. Install it with:\n"
                    "  pip install easyocr"
                )
            self._reader = easyocr.Reader(self.languages, verbose=False)
        return self._reader

    def image_to_text(self, image: object) -> tuple[str, float | None]:
        import numpy as np  # type: ignore[import]
        import io

        reader = self._get_reader()

        if PILImage and isinstance(image, PILImage.Image):
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            img_bytes = buf.getvalue()
        else:
            img_bytes = np.array(image)  # type: ignore[arg-type]

        results = reader.readtext(img_bytes)  # type: ignore[union-attr]
        if not results:
            return "", None

        texts = [r[1] for r in results]
        confs = [float(r[2]) for r in results if r[2] is not None]
        avg_conf = (sum(confs) / len(confs) * 100) if confs else None
        return " ".join(texts), avg_conf


def get_backend(name: str, **kwargs: object) -> OCRBackend:
    if name == "pytesseract":
        return PytesseractBackend(**kwargs)  # type: ignore[arg-type]
    if name == "easyocr":
        return EasyOCRBackend(**kwargs)  # type: ignore[arg-type]
    raise ValueError(f"Unknown OCR backend: {name!r}. Choose 'pytesseract' or 'easyocr'.")
