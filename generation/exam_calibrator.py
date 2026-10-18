import re
from typing import Optional, NamedTuple


class ExamConfig(NamedTuple):
    marks: int
    target_words: int
    min_words: int
    max_words: int
    pages: str
    recommended_top_k: int
    recommended_max_tokens: int
    structure_directive: str


def detect_exam_marks(text: str) -> Optional[int]:
    """
    Automatically detect the examination marks specified in the student's question.
    Handles formats like:
      - '5 marks', '5 mark', '5marks', '5mark'
      - '(10 marks)', '[10 marks]', '(10 Marks)'
      - '5M', '5m', '5 M', '5 m', '(5M)', '[10M]', '- 5m'
      - 'for 3 marks', 'for 5 marks', 'for 10 marks'
      - '10 marks question', '5 mark note', '3 marks short answer'
    Excludes clinical units like mg, ml, min, mm, mEq, mmol, mmHg, m/s, etc.
    """
    if not text:
        return None

    # Strip any appended [Instruction: ...] or metadata before inspecting
    clean_text = re.sub(r'\[Instruction:.*?\]', '', text, flags=re.DOTALL).strip()
    clean_text = clean_text.split("\n\n[Instruction:")[0].strip()

    # Pattern 1: Explicit 'mark' or 'marks'
    m1 = re.search(r'(?:\b|\()(\d{1,2})\s*(?:marks?|mark)\b(?:\))?', clean_text, re.IGNORECASE)
    if m1:
        val = int(m1.group(1))
        if 1 <= val <= 30:
            return val

    # Pattern 2: 'M' or 'm' in brackets, preceded by 'for', or after hyphen
    # Exclude medical units: mg, ml, min, mm, meq, mol, mbar, mhz, m/s, etc.
    m2 = re.search(
        r'(?:[\(\[\-]\s*|\bfor\s+)(\d{1,2})\s*[Mm]\b(?!\s*(?:g|l|in|m|eq|ol|bar|hz|s|sec|eters?|g\/|l\/|v|w|a|k|hg))',
        clean_text
    )
    if m2:
        val = int(m2.group(1))
        if 1 <= val <= 30:
            return val

    # Pattern 3: Standalone number + M at end of query, before colon, or followed by exam keywords
    m3 = re.search(
        r'\b(\d{1,2})\s*[Mm]\b(?!\s*(?:g|l|in|m|eq|ol|bar|hz|s|sec|eters?|g\/|l\/|v|w|a|k|hg))\s*(?:[\)\]:\-]|question|note|essay|answer|$)',
        clean_text
    )
    if m3:
        val = int(m3.group(1))
        if 1 <= val <= 30:
            return val

    return None


def get_exam_configuration(marks: Optional[int]) -> Optional[ExamConfig]:
    """
    Get the examination calibration configuration based on detected marks.
    Standard: 1 side of an examination paper = approx 200 handwritten words.
      - 3 marks: ~½ page = 100 words (90–120 words).
      - 5 marks: ~2½–3 pages = 500–600 words (Target: 550 words).
      - 10 marks: ~4½–5 pages = 900–1,000 words (Target: 950 words).
    """
    if marks is None:
        return None

    # Tier 1: Short Answer (<= 3 marks)
    if marks <= 3:
        structure = (
            "### EXAMINATION ANSWER SPECIFICATION: 3 MARKS (SHORT ANSWER - POINT-WISE ONLY)\n"
            "- Page-Length Standard: Approximately 1/2 handwritten examination page (Target: 100 words; Range: 90–120 words).\n"
            "- Format Requirement: STRICTLY POINT-WISE ONLY. No continuous paragraph blocks.\n"
            "- Required Structure:\n"
            "  * **Definition / Core Statement**: Authoritative clinical definition or concise statement in 1–2 bullet points.\n"
            "  * **Essential Points & Parameters**: 3 to 4 high-yield bullet points covering key physiological mechanisms, exact clinical values/ranges, or vital indications.\n"
            "- Content Precision: Keep the response compact, factual, point-wise only, citing exact clinical units, ranges, and thresholds (e.g. dosages, flow rates, pressures) documented in the excerpts. Output ONLY the answer without meta-notes, page numbers, citations, or word count declarations."
        )
        return ExamConfig(
            marks=marks,
            target_words=100,
            min_words=90,
            max_words=125,
            pages="½ page (~100 words)",
            recommended_top_k=5,
            recommended_max_tokens=600,
            structure_directive=structure
        )

    # Tier 2: Short Note (4 to 7 marks, typically 5 marks)
    elif marks <= 7:
        structure = (
            f"### EXAMINATION ANSWER SPECIFICATION: {marks} MARKS (SHORT NOTE - POINT-WISE ONLY)\n"
            "- Page-Length Standard: Approximately 2.5 to 3 handwritten examination pages (Target: 550 words; Range: 500–600 words).\n"
            "- Format Requirement: STRICTLY POINT-WISE ONLY. Do NOT write dense continuous paragraphs. Every section must consist of detailed, high-yield bullet points under clear bold headings.\n"
            "- Required Structure (bold headings with comprehensive bullet points under each):\n"
            "  1. **Introduction & Definition**: Bulleted clinical definition, physiological purpose, and role in cardiopulmonary bypass.\n"
            "  2. **Detailed Explanation & Mechanism of Action**: Detailed bulleted points explaining the working principle, physiological dynamics, and physical/biochemical rationale.\n"
            "  3. **Relevant Headings & Specifications**: Distinct bold subheadings with bulleted points for key components, circuit configurations, exact clinical parameters (e.g. flow rates, line pressures, temperatures, ACT/heparin dosing), or procedural steps.\n"
            "  4. **Clinical Considerations & Important Points**: Bulleted intraoperative precautions, monitoring checks, safety protocols, and key takeaways.\n"
            "- Clinical Accuracy & Precision: Prioritize exact numerical ranges, drug dosages (e.g. heparin IU/kg, protamine ratios), hemodynamics (e.g. CI, MAP, SVR), and circuit parameters documented in the excerpts. Systematically elaborate on the physiological and mechanical concepts documented in the text in detailed bullet points to achieve the full 500–600 word depth. Thoroughly explain *how* and *why* each mechanism functions without repetitive padding or fabricated facts. Output ONLY the answer point-wise without meta-notes, citations, or word count declarations."
        )
        return ExamConfig(
            marks=marks,
            target_words=550,
            min_words=500,
            max_words=620,
            pages="2½–3 pages (500–600 words)",
            recommended_top_k=7,
            recommended_max_tokens=1800,
            structure_directive=structure
        )

    # Tier 3: Long Essay (8+ marks, typically 10 marks)
    else:
        structure = (
            f"### EXAMINATION ANSWER SPECIFICATION: {marks} MARKS (LONG ESSAY - POINT-WISE ONLY)\n"
            "- Page-Length Standard: Approximately 4.5 to 5 handwritten examination pages (Target: 950 words; Range: 900–1,000 words).\n"
            "- Format Requirement: STRICTLY POINT-WISE ONLY. Do NOT write long continuous paragraphs or essay prose. Every section must be presented as structured, comprehensive bullet points under clear bold headings.\n"
            "- Required Comprehensive Structure (use distinct bold headings with exhaustive, detailed bullet points under each):\n"
            "  1. **Introduction & Clinical Overview**: Bulleted clinical definition, historical evolution/context in perfusion technology, and principal surgical indications.\n"
            "  2. **Classification & Types**: Bulleted systematic taxonomy, circuit configurations, design variations, and comparative features.\n"
            "  3. **Working Principle & Biophysical Mechanisms**: Detailed bulleted points on physical laws, gas exchange dynamics, fluid mechanics, or physiological regulation.\n"
            "  4. **Technical Components & Circuit Integration**: Bulleted specifications for cannulae, tubing sizes, prime volume/constituents, filters, sensors, safety alarms, and auxiliary devices.\n"
            "  5. **Clinical Application & Operative Conduct**: Step-by-step bulleted conduct from pre-bypass checks, initiation, maintenance/titration, to weaning and termination.\n"
            "  6. **Advantages & Limitations / Disadvantages**: Comparative bulleted clinical evaluation, specific benefits, and recognized drawbacks.\n"
            "  7. **Complications & Emergency Management**: Bulleted troubleshooting protocols, safety interventions, error prevention, and management of acute failures (e.g., massive air, pump failure, high line pressure).\n"
            "  8. **Conclusion & Key Takeaways**: Bulleted summary of evidence-based clinical practices and cardinal safety rules.\n"
            "- Clinical Accuracy & Precision: Emphasize exact numerical formulas, physiological thresholds, cannulae sizing/French sizes, circuit pressures, gas exchange dynamics, and anticoagulation protocols documented in the text. Ensure substantial, comprehensive bullet points under each section. Thoroughly unpack the clinical rationale, physiological consequences, and technical nuances documented in the excerpts to achieve the 900–1,000 word standard. Never fabricate medical values. Output ONLY the answer point-wise without citations, page references, or word count declarations."
        )
        return ExamConfig(
            marks=marks,
            target_words=950,
            min_words=900,
            max_words=1050,
            pages="4½–5 pages (900–1,000 words)",
            recommended_top_k=10,
            recommended_max_tokens=4096,
            structure_directive=structure
        )

