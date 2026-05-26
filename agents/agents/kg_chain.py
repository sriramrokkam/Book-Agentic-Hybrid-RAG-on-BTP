"""
agents/agents/kg_chain.py
Book reference: Chapter 8 — The Parallel Hybrid RAG Agent

Knowledge Graph retrieval chain (Chapter 8).

Steps:
  1. Generate a SPARQL SELECT query from the question using Gemini
  2. Execute the query against HANA Cloud via SPARQL_EXECUTE
  3. Retry with a broader fallback query if the first returns no rows
  4. Summarise the retrieved facts with Gemini

Returns state updates: kg_answer, kg_sparql, kg_facts.

CRITICAL: Every SPARQL triple pattern MUST be wrapped in GRAPH <iri> { ... }
          or HANA returns empty results without an error.
"""
import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from agents.state import HybridRAGState
from srv.hdb_srv import get_connection

logger = logging.getLogger(__name__)

_llm = None
_summariser = None

def _get_llm():
    global _llm
    if _llm is None:
        _llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-05-20", temperature=0.0, max_tokens=512)
    return _llm

def _get_summariser():
    global _summariser
    if _summariser is None:
        _summariser = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-05-20", temperature=0.1, max_tokens=1024)
    return _summariser

GRAPH_URI_PREFIX = "http://msds.knowledge-graph.org/MSDS_Graph/"

SPARQL_GEN_PROMPT = """You are a SPARQL expert. Generate a SPARQL SELECT query to answer
the question below using the provided ontology.

Ontology predicates available:
- msds:hasHazardCode (links Material to HazardCode)
- msds:hasExposureLimit (links Material to ExposureLimit, has msds:limitValue and msds:limitUnit)
- msds:requiresPrecaution (links Material to Precaution, has msds:precautionText)
- msds:hasSupplier (links Material to Supplier)
- msds:hazardDescription (literal on HazardCode)
- rdfs:label (name of the material)

Named graph: <{graph_uri}>
Material URI: <http://msds.knowledge-graph.org/material/{material_number}>

Rules:
1. Always wrap triple patterns with GRAPH <{graph_uri}> {{ ... }}
2. Use PREFIX msds: <http://msds.knowledge-graph.org/ontology/>
3. Use PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
4. Return only the SPARQL query, no explanation

Question: {question}

SPARQL:"""

SPARQL_FALLBACK_PROMPT = """The previous SPARQL query returned no results. Generate a simpler,
broader SPARQL query to retrieve any available information about this material.

Named graph: <{graph_uri}>
Material URI: <http://msds.knowledge-graph.org/material/{material_number}>

Return all triples about this material:

SPARQL:"""


def _execute_sparql(sparql: str) -> list:
    """Execute a SPARQL query via HANA's SPARQL_EXECUTE stored procedure."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.callproc("SPARQL_EXECUTE", [sparql, None, 1000, None, None])
        return cursor.fetchall()
    finally:
        cursor.close()


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences that Gemini sometimes adds."""
    if text.startswith("```"):
        lines = text.split("\n")
        return "\n".join(lines[1:-1]).strip()
    return text


def run_kg_chain(state: HybridRAGState) -> dict:
    """Execute the KG retrieval chain and return state updates."""
    question = state["question"]
    material_number = state["material_number"]
    graph_uri = f"{GRAPH_URI_PREFIX}{material_number}"

    try:
        # Step 1: Generate SPARQL
        gen_prompt = SPARQL_GEN_PROMPT.format(
            graph_uri=graph_uri,
            material_number=material_number,
            question=question,
        )
        sparql_response = _get_llm().invoke([HumanMessage(content=gen_prompt)])
        sparql = _strip_code_fences(sparql_response.content.strip())

        # Step 2: Execute SPARQL
        rows = _execute_sparql(sparql)

        # Step 3: Retry with fallback if empty
        if not rows:
            logger.info(
                "SPARQL returned empty, retrying with fallback for %s", material_number
            )
            fallback_prompt = SPARQL_FALLBACK_PROMPT.format(
                graph_uri=graph_uri,
                material_number=material_number,
            )
            fallback_response = _get_llm().invoke([HumanMessage(content=fallback_prompt)])
            sparql = _strip_code_fences(fallback_response.content.strip())
            rows = _execute_sparql(sparql)

        if not rows:
            return {
                "kg_answer": "",
                "kg_sparql": sparql,
                "kg_facts": [],
            }

        # Step 4: Summarise with Gemini
        facts = [str(row) for row in rows]
        facts_text = "\n".join(facts[:50])  # cap at 50 facts

        summarise_prompt = f"""You are an expert in material safety. The following facts were
retrieved from a structured knowledge graph about material {material_number}.
Use them to answer the question precisely.

Facts:
{facts_text}

Question: {question}

Answer:"""

        summary_response = _get_summariser().invoke([HumanMessage(content=summarise_prompt)])
        return {
            "kg_answer": summary_response.content,
            "kg_sparql": sparql,
            "kg_facts": facts[:50],
        }

    except Exception as e:
        logger.error("KG chain failed: %s", e)
        return {
            "kg_answer": "",
            "kg_sparql": "",
            "kg_facts": [],
            "error": f"KG chain error: {str(e)}",
        }
