"""
agents/agents/state.py
Book reference: Chapters 8 & 9 — HybridRAGState (Ch8), SupervisorState (Ch9)

Shared TypedDict state definitions for the LangGraph agents.
"""
from typing import TypedDict, List, Optional, Dict


class HybridRAGState(TypedDict):
    """State for the parallel hybrid RAG orchestrator (Chapter 8)."""
    # Input
    question: str
    material_number: str
    history: List[dict]

    # Vector chain outputs
    vector_answer: str
    vector_chunks: List[dict]

    # KG chain outputs
    kg_answer: str
    kg_sparql: str
    kg_facts: List[dict]

    # Final output
    final_answer: str
    sources: List[str]

    # Control
    error: Optional[str]


class SupervisorState(TypedDict):
    """State for the multi-agent supervisor (Chapter 9)."""
    # Input
    question: str
    material_number: str
    history: List[dict]

    # Decomposed sub-questions (set by supervisor node)
    sub_questions: Dict[str, str]       # {"hazard": "...", "compliance": "...", "safety": "..."}
    specialists_needed: List[str]        # e.g. ["hazard", "compliance"]

    # Specialist outputs
    hazard_answer: str
    compliance_answer: str
    safety_answer: str

    # Final output
    final_answer: str
    sources: List[str]

    # Control
    error: Optional[str]
