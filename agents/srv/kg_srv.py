"""
agents/srv/kg_srv.py
Book reference: Chapter 5 — Knowledge Graphs on SAP HANA Cloud

Knowledge Graph service for SAP HANA Cloud SPARQL (RDF named graphs).

Exposes:
  extract_triples(text, material_number)  -> list[dict]
  store_triples(material_number, triples) -> int
  query_graph(material_number, question)  -> dict
  delete_graph(material_number)           -> bool
  count_triples(material_number)          -> int

All public functions validate material_number against a strict regex to prevent
SPARQL injection (the equivalent of SQL injection for triple stores).

HANA SPARQL is executed via the stored procedure SPARQL_EXECUTE.
Results live in result[3] of the callproc return tuple.
Every triple pattern MUST be wrapped in GRAPH <iri> { ... } or HANA returns empty.
"""
import os
import re
import json
from .hdb_srv import get_connection
from .vertex_srv import get_llm

GRAPH_BASE = "http://msds.knowledge-graph.org/MSDS_Graph"
ONTOLOGY_BASE = "http://msds.knowledge-graph.org/ontology#"

# Only letters, digits, underscore, hyphen — no SPARQL metacharacters
MATERIAL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_material(material_number: str) -> None:
    if not MATERIAL_RE.match(material_number):
        raise ValueError(f"Invalid material number: {material_number!r}")


def graph_iri(material_number: str) -> str:
    _validate_material(material_number)
    return f"{GRAPH_BASE}/{material_number}"


def extract_triples(text: str, material_number: str) -> list[dict]:
    """
    Use Gemini to extract structured facts from MSDS text.
    Returns a list of {subject, predicate, object} dicts.
    Allowed predicates: hasHazardCode, hasExposureLimit, requiresPrecaution, hasSupplier.
    """
    _validate_material(material_number)
    llm = get_llm()
    prompt = f"""You are extracting structured facts from an MSDS (Material Safety Data Sheet) document.

Extract facts ONLY using these relationship types:
- hasHazardCode: material → GHS hazard code (e.g. H225, H319)
- hasExposureLimit: material → occupational exposure limit with value and unit
- requiresPrecaution: material → safety precaution text
- hasSupplier: material → supplier name

Material number: {material_number}

Return ONLY a JSON array of triples. Each triple must have:
- subject: the material IRI
- predicate: the property name (hasHazardCode, hasExposureLimit, requiresPrecaution, hasSupplier)
- object: the value (string)

Example:
[
  {{"subject": "ACETONE-001", "predicate": "hasHazardCode", "object": "H225"}},
  {{"subject": "ACETONE-001", "predicate": "hasHazardCode", "object": "H319"}},
  {{"subject": "ACETONE-001", "predicate": "hasExposureLimit", "object": "500 ppm TWA"}}
]

MSDS text to extract from:
{text[:3000]}

Return only the JSON array, no explanation."""

    response = llm.generate_content(prompt)
    raw = response.text.strip()
    # Strip markdown code fences Gemini sometimes adds
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    return json.loads(raw)


# Alias used by doc_srv.py
extract_triples_from_text = extract_triples


def store_triples(material_number: str, triples: list[dict]) -> int:
    """
    Store extracted triples as a named RDF graph in HANA.
    Uses two statements per triple: material→node edge + node→description literal.
    Returns the number of triples successfully stored.
    """
    _validate_material(material_number)
    if not triples:
        return 0
    graph = graph_iri(material_number)
    mat_iri = f"{GRAPH_BASE}/material/{material_number}"
    conn = get_connection()
    cursor = conn.cursor()
    stored = 0
    for triple in triples:
        predicate = triple.get("predicate", "")
        obj_value = str(triple.get("object", "")).replace("'", "\\'")
        obj_iri = f"{GRAPH_BASE}/{predicate}/{material_number}/{stored}"
        sparql_insert = f"""
            INSERT INTO GRAPH <{graph}> {{
                <{mat_iri}> <{ONTOLOGY_BASE}{predicate}> <{obj_iri}> .
                <{obj_iri}> <{ONTOLOGY_BASE}description> '{obj_value}' .
            }}
        """
        try:
            cursor.callproc("SPARQL_EXECUTE", (sparql_insert, None, None, None))
            stored += 1
        except Exception as e:
            print(f"Warning: failed to store triple {triple}: {e}")
    conn.commit()
    cursor.close()
    return stored


# Alias used by doc_srv.py
def insert_triples(conn, material_number: str, triples: list[dict]) -> int:
    """
    Version of store_triples that accepts an explicit connection (for thread-local callers).
    """
    _validate_material(material_number)
    if not triples:
        return 0
    graph = graph_iri(material_number)
    mat_iri = f"{GRAPH_BASE}/material/{material_number}"
    cursor = conn.cursor()
    stored = 0
    for triple in triples:
        predicate = triple.get("predicate", "")
        obj_value = str(triple.get("object", "")).replace("'", "\\'")
        obj_iri = f"{GRAPH_BASE}/{predicate}/{material_number}/{stored}"
        sparql_insert = f"""
            INSERT INTO GRAPH <{graph}> {{
                <{mat_iri}> <{ONTOLOGY_BASE}{predicate}> <{obj_iri}> .
                <{obj_iri}> <{ONTOLOGY_BASE}description> '{obj_value}' .
            }}
        """
        try:
            cursor.callproc("SPARQL_EXECUTE", (sparql_insert, None, None, None))
            stored += 1
        except Exception as e:
            print(f"Warning: failed to store triple {triple}: {e}")
    conn.commit()
    cursor.close()
    return stored


def query_graph(material_number: str, question: str) -> dict:
    """
    Generate a SPARQL SELECT query from the question using Gemini, execute it on HANA,
    and return {facts: list[str], sparql: str, count: int}.
    """
    _validate_material(material_number)
    graph = graph_iri(material_number)
    mat_iri = f"{GRAPH_BASE}/material/{material_number}"
    llm = get_llm()

    sparql_prompt = f"""Generate a SPARQL SELECT query to answer this question about material {material_number}.

Available predicates:
- <{ONTOLOGY_BASE}hasHazardCode> — links material to hazard code nodes
- <{ONTOLOGY_BASE}hasExposureLimit> — links material to exposure limit nodes
- <{ONTOLOGY_BASE}requiresPrecaution> — links material to precaution nodes
- <{ONTOLOGY_BASE}hasSupplier> — links material to supplier nodes
- <{ONTOLOGY_BASE}description> — literal value on any node

The material IRI is: <{mat_iri}>
The named graph is: <{graph}>

Question: {question}

Return ONLY the SPARQL query, wrapped in GRAPH clause like this:
SELECT ?value WHERE {{
  GRAPH <{graph}> {{
    <{mat_iri}> <predicate> ?node .
    ?node <{ONTOLOGY_BASE}description> ?value .
  }}
}}"""

    sparql_response = llm.generate_content(sparql_prompt)
    sparql_query = sparql_response.text.strip()
    sparql_query = re.sub(r"```sparql\s*", "", sparql_query)
    sparql_query = re.sub(r"```\s*", "", sparql_query).strip()

    conn = get_connection()
    cursor = conn.cursor()
    try:
        result = cursor.callproc("SPARQL_EXECUTE", (sparql_query, None, None, None))
        rows = result[3] if result and len(result) > 3 else []
        facts = [str(row[0]) for row in rows] if rows else []
    except Exception as e:
        facts = []
        sparql_query = f"Error: {e}"
    finally:
        cursor.close()

    return {
        "facts": facts,
        "sparql": sparql_query,
        "count": len(facts),
    }


def delete_graph(material_number: str) -> bool:
    """Drop the named graph for a material. Returns True on success."""
    _validate_material(material_number)
    graph = graph_iri(material_number)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.callproc("SPARQL_EXECUTE", (f"DROP GRAPH <{graph}>", None, None, None))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        cursor.close()
        print(f"Warning: could not delete graph {graph}: {e}")
        return False


def count_triples(material_number: str) -> int:
    """Return the total number of triples stored for a material."""
    _validate_material(material_number)
    graph = graph_iri(material_number)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        result = cursor.callproc("SPARQL_EXECUTE", (
            f"SELECT (COUNT(*) AS ?count) WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}",
            None, None, None,
        ))
        rows = result[3] if result and len(result) > 3 else []
        cursor.close()
        return int(rows[0][0]) if rows else 0
    except Exception:
        cursor.close()
        return 0


ONTOLOGY_GRAPH_IRI = "http://msds.knowledge-graph.org/ontology"


def load_ontology(ttl_path: str) -> int:
    """
    Load a Turtle (.ttl) ontology file into a dedicated HANA named graph.
    Uses SPARQL LOAD for small files; falls back to batch INSERT for large ones.

    Called once after provisioning. See Chapter 5 for ontology design details.
    Returns number of triples loaded.
    """
    with open(ttl_path, "r", encoding="utf-8") as f:
        ttl_content = f.read()

    # Parse triple count from content (rough estimate for logging)
    triple_count = ttl_content.count(" .\n") + ttl_content.count(".\n")

    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Drop existing ontology graph and recreate
        try:
            cursor.callproc("SPARQL_EXECUTE", (
                f"DROP GRAPH <{ONTOLOGY_GRAPH_IRI}>", None, None, None,
            ))
        except Exception:
            pass  # graph may not exist yet

        # Load via SPARQL UPDATE INSERT DATA using the parsed TTL
        insert_sparql = (
            f"INSERT DATA {{ GRAPH <{ONTOLOGY_GRAPH_IRI}> {{\n"
            + ttl_content
            + "\n}}"
        )
        cursor.callproc("SPARQL_EXECUTE", (insert_sparql, None, None, None))
        conn.commit()
        cursor.close()
        return triple_count
    except Exception as e:
        cursor.close()
        raise RuntimeError(f"Ontology load failed: {e}") from e
