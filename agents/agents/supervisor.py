"""
agents/agents/supervisor.py

Multi-agent supervisor — Chapter 9.

Exports:
  build_supervisor_graph()  — compile and return the LangGraph CompiledGraph
  supervisor_app            — pre-compiled instance (import-time safe; LLM is lazy)
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from agents.state import SupervisorState, HybridRAGState
from agents.kg_chain import run_kg_chain
from agents.vector_chain import run_vector_chain

logger = logging.getLogger(__name__)


# ── Lazy LLM getters ──────────────────────────────────────────────────────────

def _get_llm() -> ChatGoogleGenerativeAI:
    """Routing / specialist LLM — instantiated on first call."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-preview-05-20",
        temperature=0.0,
        max_tokens=512,
    )


def _get_summariser_llm() -> ChatGoogleGenerativeAI:
    """Synthesis LLM — instantiated on first call."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-preview-05-20",
        temperature=0.1,
        max_tokens=2048,
    )


# ── Supervisor node ────────────────────────────────────────────────────────────

SUPERVISOR_PROMPT = """You are a routing agent for a material safety data system.
Your job is to analyse a user's question and decide which specialist agents should answer it.

Available specialists:
- "hazard": answers questions about GHS hazard codes, hazard classifications, signal words, hazard statements
- "compliance": answers questions about exposure limits, regulatory thresholds, permissible concentrations, OSHA/ACGIH limits
- "safety": answers questions about precautions, first aid, PPE, storage, handling, spill response, fire fighting

For each specialist you select, write a focused sub-question that extracts only the relevant part of the user's question.

Respond in JSON format only:
{{
  "specialists": ["hazard", "compliance", "safety"],
  "sub_questions": {{
    "hazard": "What GHS hazard codes and classifications apply to {material}?",
    "compliance": "What are the worker exposure limits for {material}?",
    "safety": "What PPE and handling precautions are required for {material}?"
  }}
}}

Select only the specialists that are relevant. A simple question may need only one.

Material: {material}
Question: {question}

JSON:"""


def supervisor_node(state: SupervisorState) -> dict:
    """Decompose the user question and route sub-questions to specialist agents."""
    question = state["question"]
    material_number = state["material_number"]

    prompt = SUPERVISOR_PROMPT.format(
        material=material_number,
        question=question,
    )
    response = _get_llm().invoke([HumanMessage(content=prompt)])
    content = response.content.strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        content = "\n".join(content.split("\n")[1:-1])

    try:
        routing = json.loads(content)
        specialists = routing.get("specialists", ["hazard", "compliance", "safety"])
        sub_questions = routing.get("sub_questions", {})
        logger.info("Supervisor routed to: %s", specialists)
        logger.info("Sub-questions: %s", sub_questions)
        return {
            "specialists_needed": specialists,
            "sub_questions": sub_questions,
        }
    except json.JSONDecodeError:
        logger.warning("Supervisor JSON parse failed, routing to all specialists")
        return {
            "specialists_needed": ["hazard", "compliance", "safety"],
            "sub_questions": {
                "hazard": question,
                "compliance": question,
                "safety": question,
            },
        }


# ── Specialist helpers ─────────────────────────────────────────────────────────

def _make_chain_state(sub_question: str, state: SupervisorState) -> HybridRAGState:
    """Build a HybridRAGState for a specialist's sub-question."""
    return {
        "question": sub_question,
        "material_number": state["material_number"],
        "history": [],          # specialists don't use conversation history
        "vector_answer": "",
        "vector_chunks": [],
        "kg_answer": "",
        "kg_sparql": "",
        "kg_facts": [],
        "final_answer": "",
        "sources": [],
        "error": None,
    }


# ── Specialist agents ──────────────────────────────────────────────────────────

def hazard_agent(state: SupervisorState) -> dict:
    """KG-focused: GHS codes, classifications, hazard statements."""
    sub_q = state["sub_questions"].get("hazard", state["question"])
    chain_state = _make_chain_state(sub_q, state)
    result = run_kg_chain(chain_state)
    answer = result.get("kg_answer", "")
    if not answer:
        # Fall back to vector if KG found nothing
        vec_result = run_vector_chain(chain_state)
        answer = vec_result.get("vector_answer", "No hazard information found.")
    return {"hazard_answer": answer}


def compliance_agent(state: SupervisorState) -> dict:
    """KG-focused: exposure limits, regulatory thresholds."""
    sub_q = state["sub_questions"].get("compliance", state["question"])
    chain_state = _make_chain_state(sub_q, state)
    result = run_kg_chain(chain_state)
    answer = result.get("kg_answer", "")
    if not answer:
        vec_result = run_vector_chain(chain_state)
        answer = vec_result.get("vector_answer", "No compliance information found.")
    return {"compliance_answer": answer}


def safety_agent(state: SupervisorState) -> dict:
    """Vector-focused: precautions, first aid, PPE, storage."""
    sub_q = state["sub_questions"].get("safety", state["question"])
    chain_state = _make_chain_state(sub_q, state)
    result = run_vector_chain(chain_state)
    answer = result.get("vector_answer", "")
    if not answer:
        kg_result = run_kg_chain(chain_state)
        answer = kg_result.get("kg_answer", "No safety information found.")
    return {"safety_answer": answer}


# ── Summary agent ──────────────────────────────────────────────────────────────

def summary_agent(state: SupervisorState) -> dict:
    """Synthesise specialist answers into a final coherent response."""
    parts = []
    if state.get("hazard_answer"):
        parts.append(f"**Hazard Classification:**\n{state['hazard_answer']}")
    if state.get("compliance_answer"):
        parts.append(f"**Regulatory Compliance:**\n{state['compliance_answer']}")
    if state.get("safety_answer"):
        parts.append(f"**Safety Procedures:**\n{state['safety_answer']}")

    if not parts:
        return {
            "final_answer": (
                f"No information found for material {state['material_number']}. "
                "Please verify the material number."
            ),
            "sources": [],
        }

    if len(parts) == 1:
        # Single specialist answered — no synthesis needed
        return {
            "final_answer": parts[0].split("\n", 1)[1],
            "sources": ["Single specialist"],
        }

    combined = "\n\n".join(parts)
    prompt = f"""You are a material safety expert. Multiple specialist agents have
analysed the question below and provided their answers.

{combined}

Original question: {state['question']}

Synthesise the above into a single, well-organised, professional answer.
- Use headings to separate sections
- Do not repeat information that appears in multiple answers
- Be specific with codes, values, and units
- Write for a safety officer audience

Answer:"""

    response = _get_summariser_llm().invoke([HumanMessage(content=prompt)])
    return {
        "final_answer": response.content,
        "sources": [f"{len(parts)} specialist agents"],
    }


# ── Parallel specialists node ──────────────────────────────────────────────────

def parallel_specialists_node(state: SupervisorState) -> dict:
    """Run only the needed specialists in parallel."""
    needed = state.get("specialists_needed", ["hazard", "compliance", "safety"])

    agent_map = {
        "hazard":     hazard_agent,
        "compliance": compliance_agent,
        "safety":     safety_agent,
    }

    agents_to_run = {name: fn for name, fn in agent_map.items() if name in needed}
    results: dict = {}

    with ThreadPoolExecutor(max_workers=max(1, len(agents_to_run))) as executor:
        futures = {executor.submit(fn, state): name for name, fn in agents_to_run.items()}
        for future in as_completed(futures, timeout=60):
            name = futures[future]
            try:
                results.update(future.result(timeout=30))
            except Exception as exc:
                logger.error("Specialist %s failed: %s", name, exc)

    return results


# ── Graph construction ─────────────────────────────────────────────────────────

def build_supervisor_graph():
    """Compile and return the supervisor LangGraph."""
    graph = StateGraph(SupervisorState)

    graph.add_node("supervisor",  supervisor_node)
    graph.add_node("specialists", parallel_specialists_node)
    graph.add_node("summary",     summary_agent)

    graph.set_entry_point("supervisor")
    graph.add_edge("supervisor",  "specialists")
    graph.add_edge("specialists", "summary")
    graph.add_edge("summary",     END)

    return graph.compile()


supervisor_app = build_supervisor_graph()
