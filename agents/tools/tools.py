"""
agents/tools/tools.py
Book reference: Chapter 7 — LangGraph Fundamentals

LangChain tool definitions for optional ReAct-style agent extensions.

These tools wrap the srv layer and can be bound to an LLM via llm.bind_tools(tools).
The main hybrid RAG agent (orchestrator.py) does NOT use the ReAct pattern —
it runs both chains unconditionally in parallel. These tools are provided
for developers who want to extend the system with LLM-driven tool selection.
"""
from langchain_core.tools import tool

from srv.kg_srv import query_graph, count_triples
from srv.vector_srv import search_similar, count_vectors


@tool
def get_hazard_codes(material_number: str) -> str:
    """
    Retrieve GHS hazard codes for a material from the knowledge graph.
    Returns a comma-separated list of hazard codes (e.g. H225, H319, H336).
    """
    result = query_graph(material_number, "What are the GHS hazard codes?")
    facts = result.get("facts", [])
    return ", ".join(facts) if facts else "No hazard codes found."


@tool
def get_exposure_limits(material_number: str) -> str:
    """
    Retrieve occupational exposure limits for a material from the knowledge graph.
    Returns structured limit values with units and regulatory sources.
    """
    result = query_graph(material_number, "What are the occupational exposure limits?")
    facts = result.get("facts", [])
    return "\n".join(facts) if facts else "No exposure limits found."


@tool
def get_precautions(material_number: str) -> str:
    """
    Retrieve safety precautions for a material from the knowledge graph.
    """
    result = query_graph(material_number, "What safety precautions are required?")
    facts = result.get("facts", [])
    return "\n".join(facts) if facts else "No precautions found."


@tool
def semantic_search(question: str, material_number: str) -> str:
    """
    Perform semantic (vector) search against MSDS document chunks stored in HANA Cloud.
    Returns the top-5 most relevant passages for the question.
    """
    results = search_similar(question, material_number, top_k=5)
    if not results:
        return "No relevant passages found."
    return "\n\n---\n\n".join(
        f"[Score: {r['score']:.3f}]\n{r['chunk']}" for r in results
    )


@tool
def get_material_stats(material_number: str) -> str:
    """
    Return ingestion statistics for a material: number of vector chunks and KG triples.
    Useful for diagnosing whether a document has been successfully ingested.
    """
    vectors = count_vectors(material_number)
    triples = count_triples(material_number)
    return (
        f"Material {material_number}: "
        f"{vectors} vector chunks, {triples} KG triples."
    )


# Convenience export
ALL_TOOLS = [
    get_hazard_codes,
    get_exposure_limits,
    get_precautions,
    semantic_search,
    get_material_stats,
]
