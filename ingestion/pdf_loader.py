import hashlib
import io
try:
    import pymupdf as fitz
except ImportError:
    import fitz
from typing import List, Dict, Any, Tuple, Optional
from config import settings
from ingestion.text_cleaner import TextCleaner


class PDFProcessingError(Exception):
    """Base exception for PDF processing errors."""
    pass


class PDFValidationError(PDFProcessingError):
    """Exception raised when PDF validation fails (size, format, magic bytes)."""
    pass


class PDFReadError(PDFProcessingError):
    """Exception raised when PyMuPDF cannot read or parse the PDF."""
    pass


class ExtractedPage:
    """Container for page extraction results."""
    def __init__(self, page_number: int, raw_text: str, cleaned_text: str, is_low_text: bool):
        self.page_number = page_number  # 1-based
        self.raw_text = raw_text
        self.cleaned_text = cleaned_text
        self.is_low_text = is_low_text
        self.char_count = len(cleaned_text)


class PDFLoader:
    """
    Validates, extracts, and analyzes PDF documents using PyMuPDF (fitz).
    Preserves authentic 1-based page numbers and flags scanned/OCR-dependent files.
    """

    @staticmethod
    def validate_pdf_bytes(file_bytes: bytes, filename: str) -> None:
        """
        Validate file extension, size limit, and PDF magic bytes.
        """
        # Validate filename extension
        if not filename.lower().endswith(".pdf"):
            raise PDFValidationError(f"Invalid file extension for '{filename}'. Only .pdf files are accepted.")

        # Validate non-empty
        if not file_bytes or len(file_bytes) == 0:
            raise PDFValidationError(f"The uploaded file '{filename}' is completely empty (0 bytes).")

        # Validate size
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise PDFValidationError(
                f"File '{filename}' exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB} MB."
            )

        # Validate PDF header / magic bytes (%PDF-)
        if not file_bytes.startswith(b"%PDF-"):
            raise PDFValidationError(f"File '{filename}' is not a valid PDF document (missing %PDF- header).")

    @classmethod
    def load_and_extract(cls, file_bytes: bytes, filename: str) -> Tuple[List[ExtractedPage], Dict[str, Any]]:
        """
        Extract text from PDF pages, clean headers/footers, and assess OCR requirements.
        
        Returns:
            Tuple of (List of ExtractedPage, Document Summary dict)
        """
        cls.validate_pdf_bytes(file_bytes, filename)

        file_hash = hashlib.sha256(file_bytes).hexdigest()
        file_size = len(file_bytes)

        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
        except Exception as e:
            raise PDFReadError(f"Failed to open PDF document '{filename}': {str(e)}") from e

        try:
            if doc.is_encrypted:
                raise PDFReadError(f"Document '{filename}' is encrypted or password-protected.")

            total_pages = len(doc)
            if total_pages == 0:
                raise PDFValidationError(f"Document '{filename}' contains 0 pages.")

            raw_pages_text: List[str] = []
            for page_index in range(total_pages):
                page = doc.load_page(page_index)
                page_text = page.get_text("text") or ""
                raw_pages_text.append(page_text)

        finally:
            doc.close()

        # Clean repeated headers and footers across pages
        cleaned_pages_text = TextCleaner.strip_repeated_headers_footers(raw_pages_text)

        extracted_pages: List[ExtractedPage] = []
        low_text_pages: List[int] = []
        total_chars = 0

        for idx, (raw_text, cleaned_text) in enumerate(zip(raw_pages_text, cleaned_pages_text)):
            page_num = idx + 1  # 1-based page number
            is_low = len(cleaned_text.strip()) < settings.LOW_TEXT_PAGE_THRESHOLD
            if is_low:
                low_text_pages.append(page_num)

            total_chars += len(cleaned_text)
            extracted_pages.append(ExtractedPage(
                page_number=page_num,
                raw_text=raw_text,
                cleaned_text=cleaned_text,
                is_low_text=is_low
            ))

        # Check OCR requirement
        low_text_ratio = len(low_text_pages) / total_pages if total_pages > 0 else 1.0
        ocr_needed = False
        ocr_warning: Optional[str] = None

        if total_chars < 100:
            ocr_needed = True
            ocr_warning = (
                f"Document '{filename}' contains almost no extractable text ({total_chars} characters across {total_pages} pages). "
                "The PDF appears to be a scanned document or image-only file. An external OCR tool is required to extract searchable text."
            )
        elif low_text_ratio >= settings.OCR_PAGE_RATIO_WARNING:
            ocr_needed = True
            ocr_warning = (
                f"Document '{filename}' has {len(low_text_pages)} of {total_pages} pages with little or no extractable text. "
                "Pages may contain scanned diagrams, handwriting, or image-only scans that require OCR."
            )

        summary = {
            "filename": filename,
            "file_hash": file_hash,
            "file_size_bytes": file_size,
            "total_pages": total_pages,
            "low_text_pages": low_text_pages,
            "ocr_needed": ocr_needed,
            "ocr_warning": ocr_warning,
            "total_extracted_chars": total_chars
        }

        return extracted_pages, summary
