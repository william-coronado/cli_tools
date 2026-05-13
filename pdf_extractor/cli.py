from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pdf_extractor.cli",
        description="Extract clean text from PDF files.",
    )
    parser.add_argument("path", help="Path to a PDF file or directory of PDFs")
    parser.add_argument("--output", "-o", default=None, help="Output file (default: stdout)")
    parser.add_argument(
        "--format", choices=["markdown", "json", "text"], default="markdown"
    )
    parser.add_argument(
        "--ocr-backend", default="pytesseract", choices=["pytesseract", "easyocr"],
        dest="ocr_backend",
    )
    parser.add_argument("--ocr-language", default="eng", dest="ocr_language")
    parser.add_argument(
        "--force-ocr", action="store_true", dest="force_ocr",
        help="Always use OCR even if text layer detected",
    )
    parser.add_argument(
        "--force-text", action="store_true", dest="force_text",
        help="Always use pdfplumber; fail if no text layer",
    )
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument(
        "--pages", default=None,
        help="Page range, e.g. '1-5' or '1,3,7' (default: all)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--no-color", action="store_true", dest="no_color")

    args = parser.parse_args(argv)

    target = Path(args.path)
    if not target.exists():
        print(f"error: path does not exist: {target}", file=sys.stderr)
        return 1

    from .extractor import PDFExtractor

    extractor = PDFExtractor(
        ocr_backend=args.ocr_backend,
        ocr_language=args.ocr_language,
        dpi=args.dpi,
        verbose=args.verbose,
    )

    pdf_files: list[Path] = []
    if target.is_dir():
        pdf_files = sorted(target.glob("*.pdf"))
        if not pdf_files:
            print(f"error: no PDF files found in {target}", file=sys.stderr)
            return 1
    else:
        pdf_files = [target]

    results = []
    for pdf_path in pdf_files:
        try:
            result = extractor.extract(
                pdf_path,
                pages=args.pages,
                force_ocr=args.force_ocr,
                force_text=args.force_text,
            )
            results.append(result)
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        except PermissionError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        except RuntimeError as e:
            msg = str(e)
            if any(
                dep in msg.lower()
                for dep in ["tesseract", "poppler", "pdfplumber", "pdf2image", "easyocr"]
            ):
                print(f"error: missing dependency — {e}", file=sys.stderr)
                return 4
            print(f"error: {e}", file=sys.stderr)
            return 1

    if args.format == "json":
        if len(results) == 1:
            output = json.dumps(results[0].to_json(), indent=2)
        else:
            output = json.dumps([r.to_json() for r in results], indent=2)
    elif args.format == "text":
        output = "\n\n".join(r.to_text() for r in results)
    else:
        output = "\n\n".join(r.to_markdown() for r in results)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        if args.verbose:
            print(f"wrote {len(output)} chars to {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
