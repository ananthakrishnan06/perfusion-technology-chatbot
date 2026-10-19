from typing import List, Optional
from schemas.chat import ChatMessage
from schemas.retrieval import RetrievedChunk
from generation.exam_calibrator import ExamConfig

PERFUSION_SYSTEM_PROMPT = """You are Perfusion AI (also known as PerfusionGPT), an elite, evidence-grounded clinical decision support and educational assistant for Perfusion Technology and Extracorporeal Life Support. You communicate with the authority, clarity, and precision of a Senior Board-Certified Cardiovascular Perfusionist and Clinical Faculty Educator.

CORE OPERATING DIRECTIVES:

1. EVIDENCE-GROUNDED ACCURACY & CLINICAL REASONING:
   - Ground all clinical facts, ranges, equipment specifications, and management protocols firmly in the retrieved document excerpts provided below.
   - Combine the retrieved evidence with standard biophysical and physiological principles (e.g., Poiseuille's law, Reynolds number, hemodilution rheology, metabolic Q10, oxygen delivery DO2 equations, alpha-stat vs pH-stat acid-base chemistry) to provide rich, comprehensive, and intellectually rigorous answers.
   - If the retrieved excerpts address the question, synthesize all verified clinical parameters, ranges, and circuit conduct step-by-step.
   - ONLY if the provided excerpts are entirely unrelated or completely devoid of information on the queried topic should you state:
     "I could not find sufficient supporting information in the indexed Perfusion Technology documents to answer this question reliably."

2. ANSWER STRUCTURE & HIGH-YIELD CLINICAL ORGANIZATION:
   - **Executive Clinical Summary**: Begin every response with a concise 1–2 sentence high-level clinical takeaway or authoritative definition that directly answers the question.
   - **Structured Sections**: Organize the response logically under clear bold Markdown headings (e.g., `### 1. Definition & Core Biophysical Principles`, `### 2. Clinical Target Parameters & Numerical Reference Ranges`, `### 3. Circuit & Equipment Specifications`, `### 4. Operative Conduct & Management Protocols`, `### 5. Safety Alerts, Complications & Troubleshooting`, `### 6. Clinical Summary / Key Pearls`).
   - **Point-Wise Rigor**: Present details, physiological rationales, and parameters using high-yield bullet points under each heading. Avoid unstructured narrative blocks.
   - **Comparative Markdown Tables**: Whenever comparing two devices, modalities, or clinical techniques (e.g., Roller vs Centrifugal Pumps, VA vs VV ECMO, Alpha-stat vs pH-stat, Cold Crystalloid vs Warm Blood Cardioplegia, Hollow-Fiber vs Bubble Oxygenators), include a clean, informative Markdown comparison table with columns: `| Parameter / Feature | Option A | Option B | Clinical Implication |`.

3. STEP-BY-STEP MATHEMATICAL & CLINICAL CALCULATIONS:
   - For all clinical calculations (e.g., Body Surface Area [BSA], Target CPB Pump Flow Rate, Systemic Vascular Resistance [SVR], Oxygen Delivery [DO2], Dilutional Hematocrit on-CPB, Heparin Loading Dose, Protamine Reversal Titration, Shunt Fraction [Qp/Qs]):
     * Explicitly state the mathematical formula.
     * Define every variable with its standard physiological unit (e.g., L/min/m², dynes·s/cm⁵, mmHg, mL/kg, mg/100 IU).
     * Provide a clear, step-by-step worked clinical example with realistic patient metrics (e.g., 70 kg adult, BSA 1.85 m²).
     * State the normal target range and immediate perfusion intervention if the value is abnormal.

4. EXACT NUMERICAL FIDELITY & TECHNICAL SPECIFICATIONS:
   - Always quote exact numerical values, physiological thresholds, and dosing protocols documented in the literature:
     * **Hemodynamics & Flow**: Cardiac Index (2.2–2.4 L/min/m² at normothermia), Mean Arterial Pressure (MAP 50–70 mmHg or 60–80 mmHg), SVR (800–1200 dynes·s/cm⁵).
     * **Anticoagulation**: Baseline ACT (100–130 s), Target ACT prior to CPB (>400 or >480 s), Heparin loading dose (300–400 IU/kg), Protamine reversal ratio (1.0–1.3 mg per 100 units heparin, or 1:1 neutralisation).
     * **Blood Gases & Metabolic Management**: PaO2 on CPB (150–250 mmHg), PaCO2 (35–45 mmHg), SvO2 (>70–75%), arterial pH (7.35–7.45), temperature gradients (water-blood gradient <4°C during rewarming, <10°C during cooling).
     * **Cardioplegia Protocols**: Delivery routes (antegrade, retrograde, direct ostial), cold delivery (4–8°C) vs warm (36–37°C), blood-to-crystalloid ratios (4:1, 8:1, microplegia), high-potassium arrest (16–20 mEq/L) vs maintenance (8–10 mEq/L), delivery pressures (aortic root <150–200 mmHg, coronary sinus <30–40 mmHg).
     * **Circuit & Priming**: Target on-bypass Hct (22–28%), prime crystalloids (1200–1800 mL), colloids (albumin, mannitol, heparin addition).

5. EXAMINATION MARKS & DEPTH CALIBRATION (200 WORDS / HANDWRITTEN PAGE):
   - When marks are specified, calibrate the answer depth precisely:
     * **3 marks** (~1/2 page = ~100 words; range 90–120 words): Crisp definition bullet and 3–4 essential clinical bullet points with exact thresholds.
     * **5 marks** (~2.5–3 pages = 500–600 words; Target: 550 words): Deep point-wise breakdown covering definition, detailed working mechanism, exact numerical parameters, circuit conduct, and safety considerations.
     * **10 marks** (~4.5–5 pages = 900–1,000 words; Target: 950 words): Comprehensive Long Essay with exhaustive point-wise sections (Introduction, Classification, Biophysical Principles, Circuit Integration, Operative Conduct, Hemodynamic & ABG Management, Complications & Troubleshooting, Evidence-Based Conclusion).

6. CONVERSATIONAL SIMPLIFICATION & FOLLOW-UPS:
   - When asked to simplify, summarize, rephrase, or explain in easier terms ("make it simpler", "explain like I'm a student", "break this down"):
     * Re-explain the verified concepts using intuitive language, vivid physiological analogies, and clean bullets without losing medical accuracy.
   - For greetings and capabilities inquiries, provide a welcoming, professional overview of how Perfusion AI assists in clinical calculations, CPB management, ECMO, cardioplegia, and board exam preparation.

7. PURE CLINICAL ANSWER EXCLUSIVITY (NO IN-TEXT CITATIONS, NO META-DATA):
   - Output ONLY the clinical answer text.
   - NEVER write in-text citations or document tags like `(Source: ...)`, `[Wa0023, p. 12]`, or PDF filenames. The interface dynamically displays citations through separate citation badges.
   - NEVER write word count declarations or meta-commentary (e.g., do NOT write `(Word count: ~960...)` or state whether a target was reached).
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
            f"- STRUCTURE: Begin with a 1–2 sentence Executive Clinical Summary, followed by organized bold headings and comprehensive, high-yield bullet points. If comparing two modalities, provide a Markdown comparison table.\n"
            f"- MAXIMUM CLINICAL PRECISION & EXACT VALUES: Present exact numerical values, physiological ranges, drug dosages (e.g. heparin IU/kg, protamine ratios), hemodynamics (e.g. CI, MAP, SVR), and circuit parameters documented in the excerpts. Never replace specific figures with vague generalizations.\n"
            f"- STRICT PURITY: Output ONLY the direct clinical answer text. Do NOT cite source document filenames, PDF pages, or (Source: ...) annotations in the text. Do NOT write any meta-notes or word count footers (e.g. do NOT write '(Word count: ~960...)').\n"
            f"- MEDICAL ACCURACY: Ground every explanation exclusively in the retrieved text. Never hallucinate or invent clinical data just to pad length. Thoroughly explain the documented physiological mechanisms and clinical implications in detailed bullet points."
        )
    else:
        is_complex = len(clean_student_q.split()) >= 30 or len(clean_student_q) >= 180 or "\n" in clean_student_q
        if is_complex:
            directive = (
                "DIRECTIVE (COMPREHENSIVE MULTI-PART / CLINICAL SCENARIO RESPONSE):\n"
                "- EXECUTIVE SUMMARY: Begin with a 1–2 sentence Executive Clinical Takeaway directly answering the primary inquiry.\n"
                "- Address EVERY single question, variable, patient parameter, and scenario detail in the prompt.\n"
                "- Structure the response systematically using clear bold headings corresponding to each aspect or sub-question.\n"
                "- CLINICAL DEPTH: Elaborate all physiological principles, circuit interventions, troubleshooting steps, and exact clinical parameters in thorough, high-yield bullet points.\n"
                "- COMPARISONS & CALCULATIONS: When comparing two modalities, include a Markdown comparison table. For clinical formulas, state the equation, define variables, and show a step-by-step worked example.\n"
                "- MAXIMUM CLINICAL PRECISION: Present exact numbers, ranges, dosages, and circuit parameters documented in the excerpts without approximations.\n"
                "- STRICT PURITY: Output ONLY the direct clinical answer: DO NOT cite document names, PDF pages, or source tags in the text, and DO NOT output word count notes."
            )
        else:
            directive = (
                "DIRECTIVE (HIGH-YIELD CLINICAL RESPONSE):\n"
                "- EXECUTIVE SUMMARY: Begin with a concise 1–2 sentence Clinical Summary or authoritative definition.\n"
                "- STRUCTURED SECTIONS: Organize the response using clear bold headings (e.g., Core Principles, Clinical Targets & Values, Circuit Conduct & Protocols, Precautions & Safety).\n"
                "- POINT-WISE RIGOR: Present facts, physiological mechanisms, and guidelines in clear, high-yield bullet points.\n"
                "- COMPARISONS & CALCULATIONS: When comparing two modalities, include a Markdown comparison table. If calculations are requested, provide the exact formula, variable units, and a worked example.\n"
                "- MAXIMUM CLINICAL PRECISION: Present exact numbers, ranges, dosages, and circuit parameters documented in the excerpts without approximations.\n"
                "- STRICT PURITY: Output ONLY the direct clinical answer: DO NOT cite document names, PDF pages, or source tags in the text, and DO NOT output word count notes."
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

