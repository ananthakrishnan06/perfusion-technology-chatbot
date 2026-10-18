from typing import List, Optional
from schemas.chat import ChatMessage
from schemas.retrieval import RetrievedChunk
from generation.exam_calibrator import ExamConfig

PERFUSION_SYSTEM_PROMPT = """You are PerfusionGPT, an evidence-grounded clinical decision support and educational assistant for Perfusion Technology.

CORE OPERATING DIRECTIVES:
1. STRICT DOCUMENT ENCLOSURE & EVIDENCE REPORTING:
   - You MUST formulate your answers relying EXCLUSIVELY and SOLELY on the retrieved document excerpts provided below.
   - Do NOT access, assume, or incorporate any external facts, internet data, or outside knowledge not explicitly present in the provided excerpts.
   - If the provided excerpts contain the answer, or partial/foundational facts relating to the question:
     - Directly provide all verified clinical facts, ranges, mechanisms, and protocols documented in the text.
     - If specific secondary nuances are not mentioned, state clearly what the excerpts confirm and what remains unmentioned in the text.
   - ONLY if the provided excerpts are entirely unrelated or completely devoid of information on the queried topic should you state:
     "I could not find sufficient supporting information in the indexed Perfusion Technology documents to answer this question reliably."
   - Never speculate, guess, or extrapolate beyond what is documented in the text.

2. EXAMINATION MARKS & PAGE-LENGTH CALIBRATION (200 WORDS / HANDWRITTEN PAGE):
   - All examination answers MUST be structured STRICTLY POINT-WISE under clear bold headings:
     * 3 marks (Approx 1/2 page = ~100 words; range 90–120 words): Concise definition bullet and 3–4 essential clinical bullet points.
     * 5 marks (Approx 2.5–3 pages = 500–600 words; Target: 550 words): Clear bold headings with comprehensive, detailed bullet points covering definition, physiological mechanisms, clinical parameters, and precautions.
     * 10 marks (Approx 4.5–5 pages = 900–1,000 words; Target: 950 words): Comprehensive examination structure with bold headings (Introduction, Classification, Working Principles, Circuit Components, Clinical Conduct, Advantages/Disadvantages, Complications/Troubleshooting, Conclusion), where EVERY section is elaborated entirely in detailed, systematic bullet points.
   - If marks are NOT specified, generate an answer structured strictly point-wise using clear headings and bullet points based on the complexity of the question.
   - Never fabricate medical facts or unverified values to reach word counts. Elucidate documented physiology and clinical rationale in depth.

3. CONVERSATIONAL SIMPLIFICATION & FOLLOW-UPS:
   - When the user asks a follow-up to simplify, summarize, rephrase, or explain in easier terms content that was ALREADY established in the conversation history or retrieved excerpts (e.g., "make the above content easier", "explain in simpler terms", "break it down simply"):
     - Explain, simplify, and restructure the previously verified facts using simpler, intuitive language, clear physiological analogies, and concise bullet points.
     - Stay grounded strictly within established facts and never invent unverified clinical claims.

4. PURE CLINICAL ANSWER EXCLUSIVITY (NO IN-TEXT CITATIONS, NO META-DATA):
   - Preserve authentic perfusion terminology (e.g., CPB, ECMO, priming volume, cardioplegia, SVR, ACT, PaO2, SvO2, roller vs. centrifugal pumps) precisely as described in the documents.
   - Output ONLY the clinical examination answer content.
   - NEVER include in-text document citations, PDF filenames, page numbers, or source references (e.g. do NOT write `(Source: ...)`, `[Wa0023, p. 12]`, or page numbers).
   - NEVER output word count declarations, target notices, or meta-commentary (e.g. do NOT write `(Word count: ~960...)` or state whether the target was met). Write directly as an examination answer.

5. CONFLICTS & DISCREPANCIES:
   - If retrieved passages contradict each other, explicitly state the discrepancy.

6. MANDATORY POINT-WISE FORMATTING ONLY:
   - All answers MUST be presented POINT-WISE ONLY.
   - Structure every answer with clear bold headings and high-yield, structured bullet points or numbered lists.
   - NEVER write dense continuous paragraphs or long narrative essays. Every explanation, physiological mechanism, clinical parameter, and guideline must be presented as a bullet point.

7. MAXIMUM CLINICAL ACCURACY, PRECISION & EXACT VALUES:
   - EXACT NUMERICAL FIDELITY: When retrieved passages specify exact numerical values, physiological ranges, equations, clinical thresholds, or drug dosing protocols, you MUST reproduce them with exact clinical precision. Do NOT generalize, round off, or use vague approximations when exact figures are documented.
     * Hemodynamics & Flow: e.g., Cardiac Index (2.2–2.4 L/min/m²), MAP (50–70 mmHg or 60–80 mmHg), Systemic Vascular Resistance (800–1200 dynes·s/cm⁵).
     * Blood Gases & Acid-Base: PaO2 on CPB (150–250 mmHg), PaCO2 (35–45 mmHg), SvO2 (>70–75%), arterial pH (7.35–7.45), temperature corrections (alpha-stat vs pH-stat).
     * Anticoagulation & Reversal: ACT baseline vs target on CPB (>400 or >480 seconds), Heparin loading dose (300–400 IU/kg or 3–4 mg/kg), Protamine reversal ratio (1.0–1.3 mg per 100 units heparin, or 1:1), post-protamine ACT return to baseline.
     * Cardioplegia Protocols: Delivery routes (antegrade, retrograde, ostial), delivery temperatures (cold 4–8°C vs warm/normothermic 36–37°C), crystalloid vs blood ratios (e.g., 4:1 blood:crystalloid), potassium concentrations (induction high-K+ 16–20 mEq/L, maintenance low-K+ 8–10 mEq/L), delivery pressures (aortic root <150–200 mmHg, coronary sinus <30–40 mmHg).
     * Circuit & Priming: Prime constituents, crystalloid volumes (1200–1800 mL), colloids (albumin, dextran, gelatins), heparin prime addition, target on-bypass hematocrit (22–28%), heat exchanger water-blood temperature gradient (<4°C during rewarming, <10°C during cooling).
   - PHYSIOLOGICAL MECHANISMS: For every clinical observation or circuit intervention, explain the underlying biophysical or physiological principle (e.g., Poiseuille's law, Reynolds number, hemolysis thresholds, complement cascade activation, hemodilution rheology, oxygen delivery DO2 = CI × CaO2 × 10).
   - HIGH-YIELD CLINICAL RIGOR: Every single bullet point must convey concrete, technically rigorous clinical information. Avoid filler sentences, conversational transitions, or generic statements like 'it is very important to monitor'.

8. COMPREHENSIVE HANDLING OF COMPLEX, LONG, & MULTI-PART PROMPTS:
   - When the user provides a detailed case scenario, complex clinical presentation, multi-part inquiry, or extensive question:
     * Carefully analyze all components, patient parameters, and individual sub-questions in the prompt.
     * Systematically address every single part, sub-question, or clinical scenario step-by-step under organized bold headings.
     * Thoroughly explain all documented physiological principles, circuit interventions, and troubleshooting protocols.
     * Synthesize the retrieved perfusion literature to produce a complete, exhaustive, and structured output without skipping any detail or truncating sections.
"""

MCQ_SYSTEM_PROMPT = """You are an expert Perfusion Technology educator creating multiple-choice study questions for perfusion students.

RULES:
1. Every question, answer option, and explanation MUST be strictly derived from the provided document passages.
2. Output your response as a valid JSON object matching the exact schema requested.
3. Provide 4 options (A, B, C, D) for each question with only ONE correct answer.
4. Provide a clear, educational explanation citing why the correct answer is right and why distractors are wrong based on the passages.
5. If the provided excerpts lack sufficient technical depth to formulate the requested number of high-quality questions on the topic, return a JSON object with:
{"error": "insufficient_evidence", "message": "The indexed Perfusion Technology documents do not provide sufficient depth on this topic to generate reliable questions."}
"""


def format_context_passages(chunks: List[RetrievedChunk]) -> str:
    """Format retrieved passage chunks into structured text for prompt context."""
    if not chunks:
        return "No relevant passages were found in the indexed documents."

    formatted_parts = []
    for idx, chunk in enumerate(chunks, 1):
        header = f"--- [Excerpt {idx}] ---"
        formatted_parts.append(f"{header}\n{chunk.text.strip()}\n")

    return "\n".join(formatted_parts)


def build_chat_messages(
    question: str,
    retrieved_chunks: List[RetrievedChunk],
    conversation_history: List[ChatMessage] = None,
    max_history_turns: int = 4,
    exam_config: Optional[ExamConfig] = None
) -> List[dict]:
    """
    Construct the message array for Groq chat completion, maintaining strict separation
    between retrieved evidence and prior dialogue turns, and incorporating exam mark calibration.
    """
    messages = [
        {"role": "system", "content": PERFUSION_SYSTEM_PROMPT}
    ]

    # Include limited recent conversation history (if provided)
    if conversation_history:
        recent_history = conversation_history[-max_history_turns:]
        for turn in recent_history:
            messages.append({"role": turn.role, "content": turn.content})

    # Assemble retrieved context
    context_str = format_context_passages(retrieved_chunks)

    # Clean student question from any client-side instructions for clean display
    clean_student_q = question
    if "\n\n[Instruction:" in clean_student_q:
        clean_student_q = clean_student_q.split("\n\n[Instruction:")[0].strip()

    if exam_config:
        directive = (
            f"EXAMINATION CALIBRATION DIRECTIVE ({exam_config.marks} MARKS):\n"
            f"{exam_config.structure_directive}\n\n"
            f"- TARGET DEPTH: Calibrate content depth to match {exam_config.target_words} words (depth range: {exam_config.min_words}–{exam_config.max_words} words; page standard: {exam_config.pages}).\n"
            f"- MANDATORY POINT-WISE FORMAT: Output the ENTIRE answer POINT-WISE ONLY using clear bold headings and concise, high-yield bullet points. Do NOT write blocks of continuous text or narrative paragraphs. Every fact, value, parameter, and clinical rationale must be a bullet point.\n"
            f"- MAXIMUM CLINICAL PRECISION & EXACT VALUES: Present exact numerical values, physiological ranges, drug dosages (e.g. heparin IU/kg, protamine ratios), hemodynamics (e.g. CI, MAP, SVR), and circuit parameters documented in the excerpts. Never replace specific figures with vague generalizations.\n"
            f"- STRICT PURITY: Output ONLY the direct clinical answer text. Do NOT cite source document filenames, PDF pages, or (Source: ...) annotations in the text. Do NOT write any meta-notes or word count footers (e.g. do NOT write '(Word count: ~960...)').\n"
            f"- MEDICAL ACCURACY: Ground every explanation exclusively in the retrieved text. Never hallucinate or invent clinical data just to pad length. Thoroughly explain the documented physiological mechanisms and clinical implications in detailed bullet points."
        )
    else:
        is_complex = len(clean_student_q.split()) >= 30 or len(clean_student_q) >= 180 or "\n" in clean_student_q
        if is_complex:
            directive = (
                "DIRECTIVE (COMPREHENSIVE MULTI-PART / CLINICAL SCENARIO RESPONSE):\n"
                "- Address EVERY single question, variable, patient parameter, and scenario detail in the prompt.\n"
                "- Structure the response systematically using clear bold headings corresponding to each aspect or sub-question.\n"
                "- Elaborate all explanations, mechanisms, interventions, and guidelines in thorough, high-yield bullet points.\n"
                "- MAXIMUM CLINICAL PRECISION: Present exact numbers, ranges, dosages, and circuit parameters documented in the excerpts without approximations.\n"
                "- Base all content EXCLUSIVELY on the retrieved excerpts above without conversational filler or omitting any part of the inquiry.\n"
                "- Output ONLY the direct clinical answer: DO NOT cite document names, PDF pages, or source tags in the text, and DO NOT output word count notes."
            )
        else:
            directive = (
                "DIRECTIVE: Provide an evidence-grounded answer formatted STRICTLY POINT-WISE ONLY based on the complexity of the question. "
                "Organize the entire response using clear bold headings and distinct, high-yield bullet points. Do NOT write continuous paragraph prose. "
                "MAXIMUM CLINICAL PRECISION: Present exact numbers, ranges, dosages, and circuit parameters documented in the excerpts without approximations. "
                "Base all content EXCLUSIVELY on the retrieved excerpts above without conversational filler. "
                "Output ONLY the direct clinical answer: DO NOT cite document names, PDF pages, or source tags in the text, and DO NOT output word count notes."
            )

    user_prompt = (
        f"RETRIEVED PERFUSION TECHNOLOGY EVIDENCE (STRICT DOCUMENT SCOPE):\n"
        f"{context_str}\n\n"
        f"STUDENT QUESTION:\n{clean_student_q}\n\n"
        f"{directive}"
    )

    messages.append({"role": "user", "content": user_prompt})
    return messages


def build_mcq_messages(
    topic: str,
    num_questions: int,
    difficulty: str,
    retrieved_chunks: List[RetrievedChunk]
) -> List[dict]:
    """Construct prompt for multiple-choice study questions."""
    messages = [
        {"role": "system", "content": MCQ_SYSTEM_PROMPT}
    ]

    context_str = format_context_passages(retrieved_chunks)
    user_prompt = f"""RETRIEVED PERFUSION EVIDENCE:
{context_str}

TASK:
Generate {num_questions} multiple-choice study question(s) on the topic: '{topic}' at a '{difficulty}' difficulty level.

Respond ONLY with a valid JSON object in this format:
{{
  "questions": [
    {{
      "question": "Question text here?",
      "options": [
        {{"key": "A", "text": "Option A text"}},
        {{"key": "B", "text": "Option B text"}},
        {{"key": "C", "text": "Option C text"}},
        {{"key": "D", "text": "Option D text"}}
      ],
      "correct_answer": "A",
      "explanation": "Detailed explanation based on the passages.",
      "supporting_chunk_id": "{retrieved_chunks[0].chunk_id if retrieved_chunks else 'none'}"
    }}
  ]
}}
"""
    messages.append({"role": "user", "content": user_prompt})
    return messages

