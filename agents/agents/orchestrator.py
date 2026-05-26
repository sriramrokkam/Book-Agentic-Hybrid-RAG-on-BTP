"""
agents/agents/orchestrator.py
Book reference: Chapter 8 — The Parallel Hybrid RAG Agent

Parallel hybrid RAG orchestrator (Chapter 8).

Dispatches vector_chain and kg_chain simultaneously via ThreadPoolExecutor,
merges their results, and returns a unified state dict.

Wall-clock latency = max(vector_time, kg_time), not their sum.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from agents.state import HybridRAGState
from agents.vector_chain import run_vector_chain
from agents.kg_chain import run_kg_chain

logger = logging.getLogger(__name__)

_llm = None

def _get_llm():
    global _llm
    if _llm is None:
        _llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-05-20", temperature=0.1, max_tokens=1024)
    return _llm

CHAIN_TIMEOUT_SECONDS = 30


def merge_results(
    kg_answer: str,
    vector_answer: str,
    question: str,
    material_number: str,
) -> str:
    """
    Merge KG and vector answers into a final response.

    Cases:
      both    → synthesis LLM call (KG preferred for exact codes/limits)
      kg only → return kg_answer directly
      vector  → return vector_answer directly
      neither → graceful error message
    """
    has_kg = bool(kg_answer and kg_answer.strip())
    has_vec = bool(vector_answer and vector_answer.strip())

    if has_kg and has_vec:
        prompt = f"""You are an expert in material safety.
Two retrieval systems answered the same question. Synthesise their answers.

Knowledge Graph:
{kg_answer}

Document Search:
{vector_answer}

Question: {question}

Synthesise into one coherent answer. Prefer KG for exact codes/limits.
Answer:"""
        return _get_llm().invoke([HumanMessage(content=prompt)]).content

    return kg_answer or vector_answer or (
        f"No information found for material {material_number}. "
        "Please verify the material number or rephrase your question."
    )


def run_hybrid_rag(state: HybridRAGState) -> dict:
    """
    Dispatch both chains in parallel, merge results.
    Returns a dict of state updates suitable for merging into HybridRAGState.
    """
    chains = {
        "vector": run_vector_chain,
        "kg": run_kg_chain,
    }
    results: dict[str, dict] = {"vector": {}, "kg": {}}

    start = time.time()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(fn, state): name
            for name, fn in chains.items()
        }
        for future in as_completed(futures, timeout=CHAIN_TIMEOUT_SECONDS + 5):
            name = futures[future]
            elapsed = time.time() - start
            try:
                results[name] = future.result(timeout=CHAIN_TIMEOUT_SECONDS)
                logger.info("%s chain completed in %.2fs", name, elapsed)
            except TimeoutError:
                logger.warning("%s chain timed out after %ds", name, CHAIN_TIMEOUT_SECONDS)
                results[name] = {}
            except Exception as e:
                logger.error("%s chain raised exception: %s", name, e)
                results[name] = {}

    total = time.time() - start
    logger.info("Both chains completed in %.2fs (wall clock)", total)

    # Merge state updates from both chains
    merged_state: dict = {}
    for chain_result in results.values():
        merged_state.update(chain_result)

    # Generate final answer
    final_answer = merge_results(
        kg_answer=merged_state.get("kg_answer", ""),
        vector_answer=merged_state.get("vector_answer", ""),
        question=state["question"],
        material_number=state["material_number"],
    )
    merged_state["final_answer"] = final_answer

    # Build sources list
    sources = []
    if merged_state.get("vector_chunks"):
        sources.append(f"Document search: {len(merged_state['vector_chunks'])} passages")
    if merged_state.get("kg_facts"):
        sources.append(f"Knowledge graph: {len(merged_state['kg_facts'])} facts")
    merged_state["sources"] = sources

    return merged_state
