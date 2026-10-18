# Google Stitch Frontend Integration Guide

This guide provides the exact REST API contracts, JSON schemas, and frontend UI component specifications for connecting a **Google Stitch** frontend to the **PerfusionGPT** RAG backend.

---

## 1. Connection Overview

* **Backend Base URL (Local):** `http://127.0.0.1:8000`
* **OpenAPI Specification File:** [`openapi.json`](file:///d:/pt%20chatbot/openapi.json) *(can be directly imported into API client tools or Stitch)*
* **Interactive Docs:** `http://127.0.0.1:8000/docs`
* **CORS Settings:** Configured in `.env` via `CORS_ORIGINS=["*"]` (or set to your specific Stitch web app domain in production).

---

## 2. Core Frontend User Interfaces in Stitch

### A. Evidence-Grounded Chat Interface (`POST /api/v1/chat/ask`)

#### Request Payload
```json
{
  "question": "What is the Activated Clotting Time (ACT) requirement before cardiopulmonary bypass?",
  "top_k": 5,
  "conversation_history": [
    {
      "role": "user",
      "content": "Hello, I am studying perfusion anticoagulation."
    },
    {
      "role": "assistant",
      "content": "Welcome. I am ready to assist with evidence from your perfusion documents."
    }
  ]
}
```

#### Response Payload
```json
{
  "answer": "### Anticoagulation Protocol\n\nBefore initiating CPB, the Activated Clotting Time (ACT) must exceed **400 to 480 seconds**...\n\n*Disclaimer: Educational use only.*",
  "grounded": true,
  "insufficient_evidence": false,
  "citations": [
    {
      "source": "DOC-20250106-WA0023..pdf",
      "page": 513,
      "chunk_id": "04ff0708_p513_c0",
      "excerpt": "23. Anticoagulation for Cardiopulmonary Bypass... Gold standard for adequate anticoagulation is ACT > 480 seconds."
    }
  ],
  "retrieval": {
    "method": "hybrid_rrf",
    "retrieved_chunks": 5
  }
}
```

#### Frontend UI Rendering in Stitch:
1. **Assistant Message Bubble:** Render `response.answer` with a standard Markdown parser (supports headings, bolding, bullet points).
2. **Citations Row (Pill Buttons):**
   - Underneath the answer, render a horizontal list of clickable citation chips:
     `[📄 DOC-20250106-WA0023..pdf | Page 513]`
   - When a student clicks or hovers over a chip, open a popover/drawer displaying the verbatim `citation.excerpt`.
3. **Insufficient Evidence Alert:**
   - If `response.insufficient_evidence === true`, render an alert banner (e.g. warning color):
     *"Evidence not found in indexed documents."*

---

### B. Multiple-Choice Exam Practice UI (`POST /api/v1/study/mcq`)

#### Request Payload
```json
{
  "topic": "Membrane Oxygenators and Sweep Gas Flow",
  "num_questions": 3,
  "difficulty": "intermediate"
}
```

#### Response Payload
```json
{
  "topic": "Membrane Oxygenators and Sweep Gas Flow",
  "questions": [
    {
      "question": "Which mechanism directly governs carbon dioxide elimination during cardiopulmonary bypass?",
      "options": [
        {"key": "A", "text": "Fraction of delivered oxygen (FiO2)"},
        {"key": "B", "text": "Sweep gas flow rate"},
        {"key": "C", "text": "Arterial filter pore size"},
        {"key": "D", "text": "Venous cannula diameter"}
      ],
      "correct_answer": "B",
      "explanation": "Carbon dioxide removal is governed directly by sweep gas flow rate through the membrane oxygenator.",
      "citations": [
        {
          "source": "DOC-20250106-WA0023..pdf",
          "page": 2,
          "chunk_id": "chunk_...",
          "excerpt": "Carbon dioxide removal is regulated by sweep gas flow rate..."
        }
      ]
    }
  ],
  "total_questions": 1,
  "insufficient_evidence": false,
  "citations": [...]
}
```

#### Frontend UI Rendering in Stitch:
1. Render an interactive Quiz Card for each question.
2. Display 4 selectable radio buttons or clickable option cards (`A`, `B`, `C`, `D`).
3. Upon selecting an answer:
   - Highlight the user's choice (green if `key === correct_answer`, red if incorrect).
   - Reveal the `explanation` and supporting citation card.

---

### C. Document Knowledge Base Explorer (`GET /api/v1/documents`)

Display a dashboard showing all active textbooks and lecture notes available in the system:

```json
{
  "documents": [
    {
      "document_id": "04ff0708-e755-46ea-a2e6-b904e057bc57",
      "filename": "DOC-20250106-WA0023..pdf",
      "total_pages": 799,
      "total_chunks": 1877,
      "uploaded_at": "2026-10-16T19:10:00Z",
      "status": "indexed"
    },
    {
      "document_id": "55d16c0a-8f92-41ff-86cd-11c649607049",
      "filename": "Introduction_to_Perfusion_Technology_Frequency_Master.pdf",
      "total_pages": 23,
      "total_chunks": 23,
      "uploaded_at": "2026-10-16T19:10:00Z",
      "status": "indexed"
    }
  ],
  "total_documents": 2
}
```

---

### D. File Upload Modal (`POST /api/v1/documents/upload`)

Allow educators and students to upload new study materials:
* **Encoding:** `multipart/form-data`
* **Form key:** `files` (accepts single or multiple files with `.pdf` extension)

