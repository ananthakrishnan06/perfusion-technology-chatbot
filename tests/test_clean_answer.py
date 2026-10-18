import pytest
from generation.answer_generator import clean_generated_answer


def test_clean_generated_answer_removes_source_citations():
    raw = (
        "## Oxygenator Function\n\n"
        "Membrane oxygenators facilitate gas exchange across microporous hollow fibers (Source: Sunith Ghosh CPB.pdf, p. 6). "
        "Sweep gas regulates PaCO2 (wa0023_curriculum_textbook.pdf, p. 142), while FiO2 regulates arterial PaO2 (p. 25).\n"
        "Additional safety checks are required [Source: cpb_handbook.pdf]."
    )
    cleaned = clean_generated_answer(raw)
    assert "(Source: Sunith Ghosh CPB.pdf, p. 6)" not in cleaned
    assert "(wa0023_curriculum_textbook.pdf, p. 142)" not in cleaned
    assert "(p. 25)" not in cleaned
    assert "[Source: cpb_handbook.pdf]" not in cleaned
    assert "Membrane oxygenators facilitate gas exchange across microporous hollow fibers." in cleaned
    assert "Sweep gas regulates PaCO2, while FiO2 regulates arterial PaO2." in cleaned
    assert "Additional safety checks are required." in cleaned


def test_clean_generated_answer_removes_word_count_footers():
    raw = (
        "## Conclusion\n\n"
        "Strict adherence to perfusion protocols minimizes patient morbidity and maximizes survival.\n\n"
        "(Word count: ~960 (within the 900‑1 000‑word target).)"
    )
    cleaned = clean_generated_answer(raw)
    assert "Word count" not in cleaned
    assert "target" not in cleaned
    assert cleaned.endswith("Strict adherence to perfusion protocols minimizes patient morbidity and maximizes survival.")


def test_clean_generated_answer_various_word_count_formats():
    samples = [
        "Clinical summary.\n\n(Word count: 550 words)",
        "Clinical summary.\n\nWord count: ~550",
        "Clinical summary.\n\n**Word count**: 950 words",
        "Clinical summary.\n\n(Approx 100 words)",
        "Clinical summary.\n\n(Target: ~950 words)",
        "Clinical summary.\n\n(within the 900-1000-word target)",
    ]
    for sample in samples:
        cleaned = clean_generated_answer(sample)
        assert cleaned == "Clinical summary."


def test_clean_generated_answer_empty_and_none():
    assert clean_generated_answer("") == ""
    assert clean_generated_answer(None) == ""
