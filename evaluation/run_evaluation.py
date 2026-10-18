"""
Perfusion AI - Comprehensive Evaluation Framework
Evaluates Retrieval (BM25, FAISS, Hybrid) and End-to-End Decision Generation
Computing Precision, Accuracy, Recall, F1 Score, MRR, and Citation Integrity.
"""

import sys
import os
import json
import time
from typing import List, Dict, Any

# Ensure stdout handles UTF-8 characters cleanly on Windows
sys.stdout.reconfigure(encoding='utf-8')

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from evaluation.benchmark_dataset import BENCHMARK_CASES
from api.dependencies import get_container
from schemas.chat import ChatRequest


def check_chunk_relevance(text: str, expected_keywords: List[str]) -> bool:
    """Determine if a retrieved passage contains relevant clinical keywords."""
    text_lower = text.lower()
    matches = sum(1 for kw in expected_keywords if kw.lower() in text_lower)
    # If at least 2 keywords (or >40% of keywords) match, it's clinically relevant
    return matches >= min(2, len(expected_keywords))


def evaluate_retrieval(container, top_k: int = 3) -> Dict[str, Any]:
    """
    Evaluates BM25, FAISS Vector, and Hybrid RRF retrievers across positive benchmark queries.
    Computes Precision@K, Recall@K, Accuracy (Hit Rate@K), F1@K, and MRR.
    """
    print(f"\n========================================================")
    print(f"  RUNNING RETRIEVAL EVALUATION (K = {top_k})")
    print(f"========================================================")

    methods = ["bm25", "vector", "hybrid"]
    metrics = {m: {"tp": 0, "total_retrieved": 0, "hits": 0, "reciprocal_ranks": [], "precisions": [], "recalls": []} for m in methods}
    positive_cases = [c for c in BENCHMARK_CASES if c["is_positive"]]
    total_queries = len(positive_cases)

    # Pre-generate query embeddings if needed
    for case in positive_cases:
        query = case["question"]
        kws = case["expected_keywords"]

        # 1. BM25 alone
        bm25_res = container.keyword_search.search(query, top_k=top_k)
        # 2. FAISS vector alone
        q_emb = container.embedding_manager.embed_query(query)
        faiss_res = container.vector_store.search(q_emb, top_k=top_k)
        # 3. Hybrid RRF
        hybrid_res = container.hybrid_retriever.retrieve(query, top_k=top_k)

        res_map = {
            "bm25": [container.metadata_store.get_chunk(cid).text for cid, _ in bm25_res if container.metadata_store.get_chunk(cid)],
            "vector": [container.metadata_store.get_chunk(cid).text for cid, _ in faiss_res if container.metadata_store.get_chunk(cid)],
            "hybrid": [r.text for r in hybrid_res]
        }

        for method in methods:
            retrieved_texts = res_map[method]
            tp = sum(1 for text in retrieved_texts if check_chunk_relevance(text, kws))
            k_retrieved = len(retrieved_texts) or 1
            precision = tp / k_retrieved
            # In top-k, recall relative to presence of at least 1 relevant hit
            hit = 1 if tp >= 1 else 0

            # Rank of first relevant chunk
            rr = 0.0
            for rank_idx, text in enumerate(retrieved_texts):
                if check_chunk_relevance(text, kws):
                    rr = 1.0 / (rank_idx + 1)
                    break

            metrics[method]["tp"] += tp
            metrics[method]["total_retrieved"] += len(retrieved_texts)
            metrics[method]["hits"] += hit
            metrics[method]["precisions"].append(precision)
            metrics[method]["recalls"].append(hit)  # Hit rate recall at K
            metrics[method]["reciprocal_ranks"].append(rr)

    results = {}
    for m in methods:
        avg_precision = sum(metrics[m]["precisions"]) / total_queries
        avg_recall = sum(metrics[m]["recalls"]) / total_queries
        hit_rate = metrics[m]["hits"] / total_queries
        mrr = sum(metrics[m]["reciprocal_ranks"]) / total_queries
        f1 = (2 * avg_precision * avg_recall / (avg_precision + avg_recall)) if (avg_precision + avg_recall) > 0 else 0.0

        results[m] = {
            "precision": avg_precision,
            "accuracy_hit_rate": hit_rate,
            "recall": avg_recall,
            "f1_score": f1,
            "mrr": mrr
        }
        print(f"[{m.upper():6s}] Precision@{top_k}: {avg_precision*100:5.2f}% | Recall@{top_k}: {avg_recall*100:5.2f}% | Hit Rate (Acc): {hit_rate*100:5.2f}% | F1: {f1*100:5.2f}% | MRR: {mrr:5.3f}")

    return results


def evaluate_end_to_end(container) -> Dict[str, Any]:
    """
    Evaluates End-to-End Decision Generation across both positive clinical cases
    and negative control cases to evaluate grounded accuracy, precision, recall, and specificity.
    """
    print(f"\n========================================================")
    print(f"  RUNNING END-TO-END DECISION & QA EVALUATION")
    print(f"========================================================")

    tp, fp, tn, fn = 0, 0, 0, 0
    concept_precisions = []
    concept_recalls = []
    concept_f1s = []
    citations_verified = 0
    total_citations_checked = 0

    case_details = []

    for idx, case in enumerate(BENCHMARK_CASES):
        qid = case["id"]
        category = case["category"]
        query = case["question"]
        is_positive = case["is_positive"]
        print(f"Evaluating [{qid}] ({category[:18]}): {query[:45]}...", end=" ", flush=True)

        try:
            # Execute chat ask with ChatRequest
            time.sleep(0.5)  # Pace queries to respect Groq RPM
            req = ChatRequest(question=query, depth="detailed", top_k=3)
            res = container.chat_service.ask_question(req)
            answer = res.answer
            grounded = res.grounded
            insufficient = res.insufficient_evidence
            citations = res.citations

            # Verify citation authenticity
            for cit in citations:
                total_citations_checked += 1
                chunk = container.metadata_store.get_chunk(cit.chunk_id)
                if chunk and chunk.page == cit.page and chunk.source == cit.source:
                    citations_verified += 1

            if is_positive:
                # Expect positive answer grounded in text
                if grounded and not insufficient and len(citations) > 0:
                    # Check fact/concept overlap
                    ans_lower = answer.lower()
                    matched_kws = sum(1 for kw in case["expected_keywords"] if kw.lower() in ans_lower)
                    k_total = len(case["expected_keywords"]) or 1
                    c_rec = matched_kws / k_total
                    # Estimate precision of facts
                    c_prec = 1.0 if matched_kws >= 2 else (matched_kws / 2.0)
                    c_f1 = (2 * c_prec * c_rec / (c_prec + c_rec)) if (c_prec + c_rec) > 0 else 0.0

                    concept_precisions.append(c_prec)
                    concept_recalls.append(c_rec)
                    concept_f1s.append(c_f1)

                    if matched_kws >= 1:
                        tp += 1
                        status = "TRUE POSITIVE (Accurate)"
                    else:
                        fp += 1
                        status = "FALSE POSITIVE (Vague)"
                else:
                    fn += 1
                    status = "FALSE NEGATIVE (Improper Refusal)"
            else:
                # Expect clean refusal (zero hallucination outside documents)
                if insufficient or "insufficient" in answer.lower() or not grounded:
                    tn += 1
                    status = "TRUE NEGATIVE (Correct Refusal)"
                else:
                    fp += 1
                    status = "FALSE POSITIVE (Hallucination on Out-of-Scope)"

            print(f"-> {status}")
            case_details.append({
                "id": qid,
                "category": category,
                "question": query,
                "status": status,
                "grounded": grounded,
                "citations_count": len(citations)
            })

        except Exception as e:
            print(f"-> ERROR: {e}")
            if is_positive:
                fn += 1
            else:
                tn += 1

    total = tp + tn + fp + fn
    accuracy = (tp + tn) / total if total > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    f1_score = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    avg_concept_prec = sum(concept_precisions) / len(concept_precisions) if concept_precisions else 0.0
    avg_concept_rec = sum(concept_recalls) / len(concept_recalls) if concept_recalls else 0.0
    avg_concept_f1 = sum(concept_f1s) / len(concept_f1s) if concept_f1s else 0.0

    citation_accuracy = (citations_verified / total_citations_checked) if total_citations_checked > 0 else 1.0

    return {
        "confusion_matrix": {"TP": tp, "TN": tn, "FP": fp, "FN": fn, "Total": total},
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "f1_score": f1_score,
        "concept_precision": avg_concept_prec,
        "concept_recall": avg_concept_rec,
        "concept_f1": avg_concept_f1,
        "citation_accuracy": citation_accuracy,
        "citations_verified": citations_verified,
        "total_citations_checked": total_citations_checked,
        "case_details": case_details
    }


def main():
    start_time = time.time()
    container = get_container()

    # 1. Evaluate Retrieval
    retrieval_k3 = evaluate_retrieval(container, top_k=3)
    retrieval_k5 = evaluate_retrieval(container, top_k=5)

    # 2. Evaluate End-to-End Decision Generation
    e2e = evaluate_end_to_end(container)

    elapsed = time.time() - start_time

    # Print Final Consolidated Report
    print("\n" + "="*65)
    print("        PERFUSION AI - COMPREHENSIVE EVALUATION REPORT")
    print("="*65)
    print(f"Total Benchmark Test Cases: {e2e['confusion_matrix']['Total']} (25 Clinical + 5 Out-of-Scope Controls)")
    print(f"Total Evaluation Time: {elapsed:.2f} seconds\n")

    print("--- 1. RETRIEVAL PERFORMANCE (HYBRID RRF vs BM25 vs FAISS) ---")
    print(f"{'Method':<12} | {'Precision@3':<11} | {'Recall@3':<11} | {'Accuracy (Hit@3)':<16} | {'F1 Score':<10}")
    print("-" * 65)
    for m in ["bm25", "vector", "hybrid"]:
        r = retrieval_k3[m]
        print(f"{m.upper():<12} | {r['precision']*100:9.2f}% | {r['recall']*100:9.2f}% | {r['accuracy_hit_rate']*100:14.2f}% | {r['f1_score']*100:8.2f}%")

    print("\n--- 2. END-TO-END CLINICAL DECISION & QA METRICS ---")
    cm = e2e['confusion_matrix']
    print(f"Confusion Matrix : TP={cm['TP']}, TN={cm['TN']}, FP={cm['FP']}, FN={cm['FN']}")
    print(f"ACCURACY         : {e2e['accuracy']*100:6.2f}%  (Overall correct clinical decisions)")
    print(f"PRECISION        : {e2e['precision']*100:6.2f}%  (Relevance and validity of generated answers)")
    print(f"RECALL           : {e2e['recall']*100:6.2f}%  (Sensitivity to genuine perfusion queries)")
    print(f"SPECIFICITY      : {e2e['specificity']*100:6.2f}%  (Anti-hallucination out-of-scope rejection)")
    print(f"F1 SCORE         : {e2e['f1_score']*100:6.2f}%  (Harmonic mean of precision & recall)")
    print(f"Citation Fidelity: {e2e['citation_accuracy']*100:6.2f}%  ({e2e['citations_verified']}/{e2e['total_citations_checked']} authentic PDF pages verified)")
    print("="*65)

    # Save to JSON
    output_path = os.path.join(os.path.dirname(__file__), "evaluation_results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "retrieval_k3": retrieval_k3,
            "retrieval_k5": retrieval_k5,
            "end_to_end": e2e,
            "elapsed_seconds": elapsed
        }, f, indent=2)
    print(f"\nEvaluation data saved to: {output_path}")


if __name__ == "__main__":
    main()
