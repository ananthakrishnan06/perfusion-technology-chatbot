import re
from typing import List
from config import settings
from schemas.document import ChunkMetadata
from ingestion.pdf_loader import ExtractedPage


class StructureAwareChunker:
    """
    Splits extracted PDF pages into semantically coherent, structure-aware passages.
    Preserves document ID, source filename, 1-based original page numbers, and chunk indices.
    """

    def __init__(self, chunk_size: int = settings.CHUNK_SIZE, chunk_overlap: int = settings.CHUNK_OVERLAP):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        Estimate token count based on whitespace word count and character ratio.
        Roughly 1 word ~= 1.3 tokens.
        """
        words = text.split()
        return max(1, int(len(words) * 1.3))

    def split_into_structural_units(self, page_text: str) -> List[str]:
        """
        Break text into coherent structural units: paragraphs, headings, bullet points,
        and sentences if paragraphs are oversized.
        """
        # Split on double newlines (paragraphs)
        paragraphs = [p.strip() for p in page_text.split("\n\n") if p.strip()]

        units: List[str] = []
        for para in paragraphs:
            para_tokens = self.estimate_tokens(para)
            if para_tokens <= self.chunk_size:
                units.append(para)
            else:
                # Paragraph is longer than target chunk size; split into sentences
                sentences = re.split(r"(?<=[.!?])\s+", para)
                curr_sentence_block = []
                curr_tokens = 0

                for sent in sentences:
                    sent = sent.strip()
                    if not sent:
                        continue
                    sent_tokens = self.estimate_tokens(sent)
                    if curr_tokens + sent_tokens > self.chunk_size and curr_sentence_block:
                        units.append(" ".join(curr_sentence_block))
                        curr_sentence_block = [sent]
                        curr_tokens = sent_tokens
                    else:
                        curr_sentence_block.append(sent)
                        curr_tokens += sent_tokens

                if curr_sentence_block:
                    units.append(" ".join(curr_sentence_block))

        return units

    def chunk_page(
        self,
        page: ExtractedPage,
        document_id: str,
        source_filename: str,
        start_chunk_index: int
    ) -> List[ChunkMetadata]:
        """
        Chunk a single extracted PDF page while strictly preserving the authentic page number.
        """
        cleaned_text = page.cleaned_text.strip()
        if not cleaned_text or len(cleaned_text) < 20:
            return []

        units = self.split_into_structural_units(cleaned_text)
        if not units:
            return []

        chunks: List[ChunkMetadata] = []
        current_units: List[str] = []
        current_tokens = 0
        chunk_idx = start_chunk_index

        for unit in units:
            unit_tokens = self.estimate_tokens(unit)

            if current_tokens + unit_tokens > self.chunk_size and current_units:
                # Emit chunk
                chunk_text = "\n\n".join(current_units)
                chunk_id = f"{document_id}_p{page.page_number}_c{chunk_idx}"
                chunks.append(ChunkMetadata(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    source=source_filename,
                    page=page.page_number,
                    chunk_index=chunk_idx,
                    text=chunk_text,
                    char_count=len(chunk_text),
                    estimated_tokens=self.estimate_tokens(chunk_text)
                ))
                chunk_idx += 1

                # Calculate overlap units from tail
                overlap_units = []
                overlap_tokens = 0
                for prev_unit in reversed(current_units):
                    p_toks = self.estimate_tokens(prev_unit)
                    if overlap_tokens + p_toks <= self.chunk_overlap:
                        overlap_units.insert(0, prev_unit)
                        overlap_tokens += p_toks
                    else:
                        break

                current_units = overlap_units + [unit]
                current_tokens = overlap_tokens + unit_tokens
            else:
                current_units.append(unit)
                current_tokens += unit_tokens

        # Emit remaining units
        if current_units:
            chunk_text = "\n\n".join(current_units)
            # Avoid emitting a tiny duplicate chunk if it's identical to the previous chunk
            if not (chunks and chunks[-1].text == chunk_text):
                chunk_id = f"{document_id}_p{page.page_number}_c{chunk_idx}"
                chunks.append(ChunkMetadata(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    source=source_filename,
                    page=page.page_number,
                    chunk_index=chunk_idx,
                    text=chunk_text,
                    char_count=len(chunk_text),
                    estimated_tokens=self.estimate_tokens(chunk_text)
                ))

        return chunks

    def chunk_document(
        self,
        pages: List[ExtractedPage],
        document_id: str,
        source_filename: str
    ) -> List[ChunkMetadata]:
        """
        Chunk all extracted pages of a document.
        """
        all_chunks: List[ChunkMetadata] = []
        global_chunk_idx = 0

        for page in pages:
            page_chunks = self.chunk_page(
                page=page,
                document_id=document_id,
                source_filename=source_filename,
                start_chunk_index=global_chunk_idx
            )
            all_chunks.extend(page_chunks)
            global_chunk_idx += len(page_chunks)

        return all_chunks

