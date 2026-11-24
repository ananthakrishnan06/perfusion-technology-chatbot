"""Serve PDF pages as images so uploaded PDF code never runs in the browser."""
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import Response


def render_pdf_page(path: Path, page: int) -> Response:
    import pymupdf
    try:
        with pymupdf.open(path) as pdf:
            if not 1 <= page <= len(pdf):
                raise HTTPException(404, "Page not found.")
            sheet = pdf[page - 1]
            scale = min(1.25, 1600 / max(sheet.rect.width, sheet.rect.height, 1))
            image = sheet.get_pixmap(matrix=pymupdf.Matrix(scale, scale)).tobytes("png")
    except (RuntimeError, ValueError):
        raise HTTPException(422, "The PDF page could not be rendered.")
    return Response(image, media_type="image/png", headers={"Cache-Control": "no-store"})
