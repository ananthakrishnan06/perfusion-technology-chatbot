import re
from typing import List, Dict
from collections import Counter


class TextCleaner:
    """
    Cleans and normalizes text extracted from medical PDFs while preserving
    critical clinical terminology, numbers, equations, and paragraph structure.
    """

    @staticmethod
    def normalize_whitespace(text: str) -> str:
        """
        Normalize excessive spaces and tabs without destroying paragraph breaks.
        """
        if not text:
            return ""

        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Normalize non-breaking spaces and irregular unicode whitespaces
        text = re.sub(r"[\u00A0\u1680\u2000-\u200B\u202F\u205F\u3000]", " ", text)

        # Replace horizontal tabs with single space
        text = text.replace("\t", " ")

        # Collapse multiple horizontal spaces into one (leaving newlines intact)
        text = re.sub(r"[^\S\n]+", " ", text)

        # Collapse 3 or more consecutive newlines into 2 (paragraph break)
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Fix hyphenation across line breaks (e.g., "perfu-\nsion" -> "perfusion")
        text = re.sub(r"(\b[a-zA-Z]{2,})-\n([a-zA-Z]{2,}\b)", r"\1\2", text)

        # Trim leading and trailing whitespace
        return text.strip()

    @classmethod
    def strip_repeated_headers_footers(cls, page_texts: List[str], min_pages: int = 3, threshold: float = 0.6) -> List[str]:
        """
        Identify and remove repeated headers and footers across pages only when
        confidently identified (e.g., matching string on >= 60% of pages).
        """
        if len(page_texts) < min_pages:
            return [cls.normalize_whitespace(p) for p in page_texts]

        first_lines = []
        last_lines = []

        for p in page_texts:
            lines = [ln.strip() for ln in p.split("\n") if ln.strip()]
            if len(lines) >= 3:  # Only evaluate pages with sufficient lines
                first_lines.append(lines[0])
                last_lines.append(lines[-1])

        repeated_headers = set()
        repeated_footers = set()

        num_samples = len(first_lines)
        if num_samples >= min_pages:
            header_counts = Counter(first_lines)
            for header, count in header_counts.items():
                if count / num_samples >= threshold and len(header) > 3:
                    # Check that header doesn't look like general text / paragraph
                    repeated_headers.add(header)

        num_last = len(last_lines)
        if num_last >= min_pages:
            footer_counts = Counter(last_lines)
            for footer, count in footer_counts.items():
                if count / num_last >= threshold and len(footer) > 1:
                    repeated_footers.add(footer)

        cleaned_pages = []
        for p in page_texts:
            lines = p.split("\n")
            cleaned_lines = []
            for idx, line in enumerate(lines):
                stripped = line.strip()
                # Skip first line if in repeated headers
                if idx == 0 and stripped in repeated_headers:
                    continue
                # Skip last line if in repeated footers
                if idx == len(lines) - 1 and stripped in repeated_footers:
                    continue
                cleaned_lines.append(line)

            cleaned_text = "\n".join(cleaned_lines)
            cleaned_pages.append(cls.normalize_whitespace(cleaned_text))

        return cleaned_pages

