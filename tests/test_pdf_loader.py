import pytest
from ingestion.pdf_loader import PDFLoader, PDFValidationError, PDFReadError
from ingestion.text_cleaner import TextCleaner
from config import settings


def test_pdf_loader_valid_extraction(sample_perfusion_pdf_bytes):
    """Test extracting text from a valid multi-page perfusion PDF."""
    pages, summary = PDFLoader.load_and_extract(sample_perfusion_pdf_bytes, "perfusion_basics.pdf")

    assert summary["filename"] == "perfusion_basics.pdf"
    assert summary["total_pages"] == 3
    assert len(pages) == 3
    assert summary["ocr_needed"] is False
    assert summary["ocr_warning"] is None

    # Verify 1-based page numbers
    assert pages[0].page_number == 1
    assert pages[1].page_number == 2
    assert pages[2].page_number == 3

    # Verify extracted medical content on respective pages
    assert "Cardiopulmonary bypass" in pages[0].cleaned_text
    assert "roller pumps" in pages[0].cleaned_text.lower()
    assert "centrifugal pumps" in pages[0].cleaned_text.lower()

    assert "Membrane Oxygenators" in pages[1].cleaned_text
    assert "sweep gas" in pages[1].cleaned_text.lower()

    assert "Anticoagulation" in pages[2].cleaned_text
    assert "Activated Clotting Time" in pages[2].cleaned_text
    assert "protamine" in pages[2].cleaned_text.lower()


def test_pdf_loader_scanned_ocr_detection(sample_scanned_pdf_bytes):
    """Test that scanned or image-only PDFs trigger OCR warnings."""
    pages, summary = PDFLoader.load_and_extract(sample_scanned_pdf_bytes, "scanned_handbook.pdf")

    assert summary["total_pages"] == 2
    assert summary["ocr_needed"] is True
    assert summary["ocr_warning"] is not None
    assert "OCR" in summary["ocr_warning"]


def test_pdf_loader_invalid_extension():
    """Test rejection of non-PDF file extensions."""
    with pytest.raises(PDFValidationError) as exc:
        PDFLoader.load_and_extract(b"%PDF-1.4 dummy", "notes.docx")
    assert "Only .pdf files are accepted" in str(exc.value)


def test_pdf_loader_empty_file():
    """Test rejection of completely empty 0-byte files."""
    with pytest.raises(PDFValidationError) as exc:
        PDFLoader.load_and_extract(b"", "empty.pdf")
    assert "completely empty" in str(exc.value)


def test_pdf_loader_invalid_magic_bytes():
    """Test rejection of files that lack the %PDF- header."""
    fake_bytes = b"NOT_A_PDF_FILE_JUST_RANDOM_DATA"
    with pytest.raises(PDFValidationError) as exc:
        PDFLoader.load_and_extract(fake_bytes, "corrupt.pdf")
    assert "missing %PDF- header" in str(exc.value)


def test_pdf_loader_size_limit():
    """Test rejection of files exceeding the maximum upload size limit."""
    original_limit = settings.MAX_UPLOAD_SIZE_MB
    try:
        # Set limit artificially low for testing
        settings.MAX_UPLOAD_SIZE_MB = 1
        one_point_five_mb = b"%PDF-1.5 " + b"0" * (int(1.5 * 1024 * 1024))
        with pytest.raises(PDFValidationError) as exc:
            PDFLoader.load_and_extract(one_point_five_mb, "large.pdf")
        assert "exceeds maximum allowed size" in str(exc.value)
    finally:
        settings.MAX_UPLOAD_SIZE_MB = original_limit


def test_text_cleaner_whitespace_and_hyphenation():
    """Test whitespace normalization and hyphen repair across line breaks."""
    raw = "Extracorporeal  membrane\t\toxgenation\r\n\r\n\r\nand perfu-\nsion circuit."
    cleaned = TextCleaner.normalize_whitespace(raw)
    assert "perfusion" in cleaned
    assert "  " not in cleaned
    assert "\t" not in cleaned
    assert "\r" not in cleaned
    assert "\n\n\n" not in cleaned


def test_text_cleaner_repeated_header_removal():
    """Test that repeated headers are identified and removed across multi-page documents."""
    page_texts = [
        "PERFUSION HANDBOOK CHAPTER 1\nContent of page 1 about CPB circuits.\nPage 1 Footer",
        "PERFUSION HANDBOOK CHAPTER 1\nContent of page 2 about roller pumps.\nPage 2 Footer",
        "PERFUSION HANDBOOK CHAPTER 1\nContent of page 3 about gas exchange.\nPage 3 Footer",
        "PERFUSION HANDBOOK CHAPTER 1\nContent of page 4 about heparin dosage.\nPage 4 Footer",
    ]

    cleaned_pages = TextCleaner.strip_repeated_headers_footers(page_texts, min_pages=3, threshold=0.6)
    assert len(cleaned_pages) == 4
    for cp in cleaned_pages:
        assert "PERFUSION HANDBOOK CHAPTER 1" not in cp
        assert "Content of page" in cp

