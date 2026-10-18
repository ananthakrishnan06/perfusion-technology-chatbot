import sys
from pathlib import Path
from api.dependencies import get_document_service


def ingest_file(pdf_path: Path, doc_service):
    if not pdf_path.exists():
        print(f"Error: File not found at '{pdf_path}'")
        return False

    if not pdf_path.name.lower().endswith(".pdf"):
        print(f"Skipping non-PDF file: '{pdf_path.name}'")
        return False

    print(f"\nProcessing '{pdf_path.name}'...")
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    result = doc_service.process_pdf_file(file_bytes, pdf_path.name)

    print(f"  Status:       {result.processing_status}")
    print(f"  Document ID:  {result.document_id}")
    print(f"  Pages:        {result.page_count}")
    print(f"  Chunks:       {result.chunk_count}")
    if result.ocr_warning:
        print(f"  [!] Warning:  {result.ocr_warning}")
    if result.error_details:
        print(f"  [!] Error:    {result.error_details}")
    return result.processing_status in ("indexed", "already_indexed")


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("pdfs")
    doc_service = get_document_service()

    if target.is_dir():
        # Case-insensitive deduplication of PDF files
        seen_paths = set()
        pdf_files = []
        for pattern in ("*.pdf", "*.PDF"):
            for f in target.glob(pattern):
                resolved = f.resolve()
                if resolved not in seen_paths:
                    seen_paths.add(resolved)
                    pdf_files.append(f)
        pdf_files.sort(key=lambda p: p.name.lower())
        if not pdf_files:
            print(f"No PDF files found in '{target.resolve()}'.")
            print("Please drop your PDF files into the 'pdfs/' folder and re-run.")
            return

        print(f"Found {len(pdf_files)} PDF file(s) in '{target}':")
        for f in pdf_files:
            print(f"  - {f.name}")

        success_count = 0
        for f in pdf_files:
            if ingest_file(f, doc_service):
                success_count += 1

        print(f"\nIngestion complete! Successfully processed {success_count}/{len(pdf_files)} files.")
        list_res = doc_service.list_documents()
        print(f"Total active indexed documents in knowledge base: {list_res.total_documents}")

    elif target.is_file():
        ingest_file(target, doc_service)
    else:
        print(f"Error: Path '{target}' does not exist.")


if __name__ == "__main__":
    main()
