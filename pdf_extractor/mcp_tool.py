from __future__ import annotations

import json
import sys


TOOL_DEFINITIONS = [
    {
        "name": "extract_pdf_text",
        "description": (
            "Extract clean text from a PDF file. Automatically detects whether the PDF "
            "has a text layer or requires OCR. Returns structured markdown with page markers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the PDF file.",
                },
                "pages": {
                    "type": "string",
                    "description": "Optional page range, e.g. '1-5' or '1,3,7'. Default: all pages.",
                },
                "force_ocr": {
                    "type": "boolean",
                    "description": "Force OCR even if text layer is detected. Default: false.",
                },
            },
            "required": ["pdf_path"],
        },
    }
]


def _handle(params: dict) -> str:
    from pathlib import Path
    from .extractor import PDFExtractor

    pdf_path = params["pdf_path"]
    pages = params.get("pages")
    force_ocr = bool(params.get("force_ocr", False))

    extractor = PDFExtractor()
    result = extractor.extract(Path(pdf_path), pages=pages, force_ocr=force_ocr)
    return result.to_markdown()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            name = request.get("name")
            params = request.get("parameters", {})
            if name == "extract_pdf_text":
                result = _handle(params)
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})
            response = {"result": result}
        except Exception as e:
            response = {"error": str(e)}
        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
