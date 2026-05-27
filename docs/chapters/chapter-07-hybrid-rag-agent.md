# Chapter 7: The Parallel Hybrid RAG Agent

In Chapter 6 we built a LangGraph agent with a stub retriever — a placeholder that returned a fixed string instead of real data. In Chapters 3 and 4 we built the real retrieval systems: a vector store in SAP HANA Cloud and a knowledge graph queried via SPARQL. In Chapter 5 we built the ingestion pipeline that populates both. All the pieces exist. This chapter assembles them.

The central design question is: when a user asks a question, do we run vector search first and knowledge graph search second? Or do we ask the LLM to decide which one to use? The answer to both is no. We run them in parallel, always, regardless of the question. This chapter explains why that decision is correct and shows you exactly how to implement it.

By the end of this chapter you will have a working hybrid RAG system: a FastAPI service that receives a natural language question, dispatches it simultaneously to both retrieval chains, merges the results, and returns an answer that demonstrably outperforms either strategy alone.

---

## 7.1 Why parallel beats sequential

Consider the naive approach: run vector search, check the result, then decide whether to also run KG search. This is sequential routing, and it has a hidden cost.

| Approach | Wall-clock time | LLM calls | Risk |
|---|---|---|---|
| Sequential: vector then KG | 2 s + 2 s = 4 s | 3 (route + vector + KG) | Routing LLM makes wrong choice |
| Sequential: KG then vector | 2 s + 2 s = 4 s | 3 | Same risk |
| Routing: LLM decides which to use | 1 s + 2 s = 3 s | 2 | Routing LLM skips useful path |
| **Parallel: both simultaneously** | **max(2 s, 2 s) = 2 s** | **2** | **None** |

The parallel approach is faster than all sequential variants and uses fewer LLM calls than the routing variant. More importantly, it eliminates the routing error entirely. A routing LLM might decide that "what are the GHS codes for acetone?" is a structured query and skip the vector chain — missing the handling instructions that live only in prose. By always running both, we guarantee that no retrieval path is skipped.

![Parallel Orchestrator Architecture](docs/screenshots/diagrams/08-parallel-orchestrator.png)
*Figure: The parallel hybrid RAG orchestrator — both chains run concurrently via ThreadPoolExecutor. Wall-clock latency equals the slower of the two chains, not their sum.*

> **Note:** This design assumes both chains have roughly similar latency (~1–3 seconds each). If one chain were orders of magnitude slower than the other, you might reconsider. In practice, a HANA SPARQL query and a HANA vector search take comparable time.

---

## 7.2 The agent state

Create `agents/agents/state.py`:

```python
from typing import TypedDict, List, Optional

class HybridRAGState(TypedDict):
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
```

This state is the contract between every component in the system. The vector chain writes to `vector_answer` and `vector_chunks`. The KG chain writes to `kg_answer`, `kg_sparql`, and `kg_facts`. The merge function reads all four and writes `final_answer`.

---

## 7.3 The vector chain

Create `agents/agents/vector_chain.py`:

```python
import logging
from typing import Optional
from langchain_google_vertexai import ChatVertexAI, VertexAIEmbeddings
from langchain_core.messages import HumanMessage

from agents.state import HybridRAGState
from srv.hdb_srv import get_connection

logger = logging.getLogger(__name__)

_llm = ChatVertexAI(model_name="gemini-1.5-pro", temperature=0.1, max_tokens=1024)
_embedder = VertexAIEmbeddings(model_name="text-embedding-004")

COSINE_SEARCH_SQL = """
SELECT TOP 5
    CHUNK_TEXT,
    MATERIAL_NUMBER,
    CHUNK_INDEX,
    TO_DOUBLE(COSINE_SIMILARITY(EMBEDDING, TO_REAL_VECTOR(?))) AS SCORE
FROM MSDS_VECTORS
WHERE MATERIAL_NUMBER = ?
ORDER BY SCORE DESC
"""

def run_vector_chain(state: HybridRAGState) -> dict:
    """Execute the vector retrieval chain and return state updates."""
    question = state["question"]
    material_number = state["material_number"]

    try:
        # Step 1: Embed the question
        embedding = _embedder.embed_query(question)
        embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

        # Step 2: Cosine search in HANA
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(COSINE_SEARCH_SQL, (embedding_str, material_number))
        rows = cursor.fetchall()

        if not rows:
            logger.info("Vector search returned no results for %s", material_number)
            return {
                "vector_answer": "",
                "vector_chunks": [],
            }

        chunks = [
            {
                "text": row[0],
                "material_number": row[1],
                "chunk_index": row[2],
                "score": float(row[3]),
            }
            for row in rows
        ]

        # Step 3: Summarise with Gemini
        context = "\n\n---\n\n".join(c["text"] for c in chunks)
        prompt = f"""You are an expert in material safety. Use the following passages
from an MSDS document to answer the question. Be specific and concise.
If the passages do not contain enough information, say so.

Passages:
{context}

Question: {question}

Answer:"""

        response = _llm.invoke([HumanMessage(content=prompt)])
        return {
            "vector_answer": response.content,
            "vector_chunks": chunks,
        }

    except Exception as e:
        logger.error("Vector chain failed: %s", e)
        return {
            "vector_answer": "",
            "vector_chunks": [],
            "error": f"Vector chain error: {str(e)}",
        }
```

Three steps: embed the question into a 768-dimensional vector, run a cosine similarity search against `MSDS_VECTORS`, summarise the top-5 matching chunks with Gemini. The SQL uses HANA's `COSINE_SIMILARITY` function and `TO_REAL_VECTOR` to cast the embedding string to the correct column type.

---

## 7.4 The KG chain

Create `agents/agents/kg_chain.py`:

```python
import logging
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage

from agents.state import HybridRAGState
from srv.hdb_srv import get_connection

logger = logging.getLogger(__name__)

_llm = ChatVertexAI(model_name="gemini-1.5-pro", temperature=0.0, max_tokens=512)
_summariser = ChatVertexAI(model_name="gemini-1.5-pro", temperature=0.1, max_tokens=1024)

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
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.callproc("SPARQL_EXECUTE", [sparql, None, 1000, None, None])
        return cursor.fetchall()
    finally:
        cursor.close()

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
        sparql_response = _llm.invoke([HumanMessage(content=gen_prompt)])
        sparql = sparql_response.content.strip()
        # Strip markdown code fences if present
        if sparql.startswith("```"):
            sparql = "\n".join(sparql.split("\n")[1:-1])

        # Step 2: Execute SPARQL
        rows = _execute_sparql(sparql)

        # Step 3: Retry with fallback if empty
        if not rows:
            logger.info("SPARQL returned empty, retrying with fallback for %s", material_number)
            fallback_prompt = SPARQL_FALLBACK_PROMPT.format(
                graph_uri=graph_uri,
                material_number=material_number,
            )
            fallback_response = _llm.invoke([HumanMessage(content=fallback_prompt)])
            sparql = fallback_response.content.strip()
            if sparql.startswith("```"):
                sparql = "\n".join(sparql.split("\n")[1:-1])
            rows = _execute_sparql(sparql)

        if not rows:
            return {
                "kg_answer": "",
                "kg_sparql": sparql,
                "kg_facts": [],
            }

        # Step 4: Summarise with Gemini
        facts = [str(row) for row in rows]
        facts_text = "\n".join(facts[:50])  # limit to 50 facts

        summarise_prompt = f"""You are an expert in material safety. The following facts were
retrieved from a structured knowledge graph about material {material_number}.
Use them to answer the question precisely.

Facts:
{facts_text}

Question: {question}

Answer:"""

        summary_response = _summariser.invoke([HumanMessage(content=summarise_prompt)])
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
```

The KG chain has one critical feature beyond basic SPARQL execution: the retry-on-empty loop. When Gemini generates a SPARQL query that returns no rows — which happens when the generated query is overly specific — the chain retries with a simpler fallback query that retrieves all triples for the material. This ensures we always get *something* from the knowledge graph if data exists.

> **Warning:** Never share HANA connections across threads. The `get_connection()` call in both chains uses `threading.local()` under the hood — each thread gets its own connection. If you pass a connection object between threads, HANA will raise concurrency errors. See `agents/srv/hdb_srv.py` for the thread-local implementation.

---

## 7.5 The merge function

The merge function is the heart of hybrid RAG. It receives whatever the two chains produced and decides how to combine them.

```python
def merge_results(
    kg_answer: str,
    vector_answer: str,
    question: str,
    material_number: str,
    llm: ChatVertexAI,
) -> str:
    """
    Merge KG and vector answers into a final response.

    Cases:
      both    → synthesis LLM call
      kg only → return kg_answer directly
      vector  → return vector_answer directly
      neither → graceful error message
    """
    has_kg = bool(kg_answer and kg_answer.strip())
    has_vec = bool(vector_answer and vector_answer.strip())

    if has_kg and has_vec:
        synthesis_prompt = f"""You are an expert in material safety.
You have received answers from two independent retrieval systems for the question below.

Structured Knowledge Graph answer:
{kg_answer}

Document Search answer:
{vector_answer}

Synthesise both into a single, coherent, well-organised answer.
- Do not repeat information
- If they contradict, prefer the structured KG answer for specific facts (codes, limits)
- If they complement, combine them naturally
- Be concise

Question: {question}

Answer:"""
        response = llm.invoke([HumanMessage(content=synthesis_prompt)])
        return response.content

    elif has_kg:
        return kg_answer

    elif has_vec:
        return vector_answer

    else:
        return (
            f"I could not find specific information about your question in the available "
            f"MSDS documents for material {material_number}. Please verify the material "
            f"number or rephrase your question."
        )
```

Four cases, handled explicitly. When both chains return results, a third Gemini call synthesises them — preferring the KG answer for precise facts and the vector answer for narrative context. When only one chain returns results, we return it directly without the overhead of a synthesis call. When neither chain returns results, we return a clear, actionable error message rather than hallucinating.

---

## 7.6 The orchestrator

Create `agents/agents/orchestrator.py`:

```python
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage

from agents.state import HybridRAGState
from agents.vector_chain import run_vector_chain
from agents.kg_chain import run_kg_chain

logger = logging.getLogger(__name__)

_llm = ChatVertexAI(model_name="gemini-1.5-pro", temperature=0.1, max_tokens=1024)

CHAIN_TIMEOUT_SECONDS = 30

def merge_results(kg_answer: str, vector_answer: str,
                  question: str, material_number: str) -> str:
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
        return _llm.invoke([HumanMessage(content=prompt)]).content

    return kg_answer or vector_answer or (
        f"No information found for material {material_number}. "
        "Please verify the material number or rephrase your question."
    )

def run_hybrid_rag(state: HybridRAGState) -> dict:
    """
    Dispatch both chains in parallel, merge results.
    Returns a dict of state updates.
    """
    chains = {
        "vector": run_vector_chain,
        "kg": run_kg_chain,
    }
    results = {"vector": {}, "kg": {}}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(fn, state): name
            for name, fn in chains.items()
        }
        for future in as_completed(futures, timeout=CHAIN_TIMEOUT_SECONDS + 5):
            name = futures[future]
            try:
                results[name] = future.result(timeout=CHAIN_TIMEOUT_SECONDS)
            except TimeoutError:
                logger.warning("%s chain timed out after %ds", name, CHAIN_TIMEOUT_SECONDS)
                results[name] = {}
            except Exception as e:
                logger.error("%s chain raised exception: %s", name, e)
                results[name] = {}

    # Merge state updates from both chains
    merged_state = {}
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
```

The orchestrator submits both chains to a `ThreadPoolExecutor` with `max_workers=2` and collects results as they complete. The `as_completed()` call returns futures in completion order — whichever chain finishes first is processed first. The 30-second timeout prevents a slow chain from blocking the response indefinitely.

> **Note:** We use `as_completed()` rather than `executor.map()` because we want to process results as soon as they arrive, not wait for all to finish. If the vector chain finishes in 1.5 seconds and the KG chain takes 3 seconds, the orchestrator captures the vector result at 1.5 seconds and the KG result at 3 seconds, then merges at ~3 seconds total.

---

## 7.7 The FastAPI /query endpoint

Add the endpoint to `agents/main.py`:

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, validator
from typing import List, Optional
import re

from agents.orchestrator import run_hybrid_rag
from agents.state import HybridRAGState

app = FastAPI(title="Hybrid RAG Agent")

MATERIAL_RE = re.compile(r"^[A-Za-z0-9_-]+$")

class QueryRequest(BaseModel):
    question: str
    material_number: str
    history: List[dict] = []

    @validator("material_number")
    def validate_material(cls, v):
        if not MATERIAL_RE.match(v):
            raise ValueError("material_number contains invalid characters")
        return v

    @validator("question")
    def validate_question(cls, v):
        if not v.strip():
            raise ValueError("question must not be empty")
        return v.strip()

class QueryResponse(BaseModel):
    answer: str
    kg_sparql: Optional[str] = None
    kg_facts: Optional[List] = None
    vector_chunks: Optional[List] = None
    sources: Optional[List[str]] = None

@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    state: HybridRAGState = {
        "question": request.question,
        "material_number": request.material_number,
        "history": request.history,
        "vector_answer": "",
        "vector_chunks": [],
        "kg_answer": "",
        "kg_sparql": "",
        "kg_facts": [],
        "final_answer": "",
        "sources": [],
        "error": None,
    }

    result = run_hybrid_rag(state)

    if not result.get("final_answer"):
        raise HTTPException(status_code=500, detail="Agent returned no answer")

    return QueryResponse(
        answer=result["final_answer"],
        kg_sparql=result.get("kg_sparql"),
        kg_facts=result.get("kg_facts"),
        vector_chunks=result.get("vector_chunks"),
        sources=result.get("sources"),
    )
```

The endpoint validates the material number against `^[A-Za-z0-9_-]+$` — the same regex used throughout the application. This prevents SPARQL injection: a material number like `ACE001> } INSERT { <evil> }` would fail validation before reaching HANA.

---

## 7.8 The full request/response contract

```json
// Request
POST /query
Content-Type: application/json

{
  "question": "What are the GHS hazard codes for acetone?",
  "material_number": "ACE001",
  "history": [
    {"role": "user",      "content": "What is acetone used for?"},
    {"role": "assistant", "content": "Acetone is a common solvent used in..."}
  ]
}

// Response
{
  "answer": "The GHS hazard codes for acetone are H225 (Highly flammable liquid and vapour), H319 (Causes serious eye irritation), and H336 (May cause drowsiness or dizziness).",
  "kg_sparql": "PREFIX msds: <...>\nSELECT ?code ?desc WHERE { GRAPH <...> { <...ACE001> msds:hasHazardCode ?hc . ?hc rdfs:label ?code . ?hc msds:hazardDescription ?desc } }",
  "kg_facts": [
    "('H225', 'Highly flammable liquid and vapour')",
    "('H319', 'Causes serious eye irritation')",
    "('H336', 'May cause drowsiness or dizziness')"
  ],
  "vector_chunks": [
    {"text": "Section 2: Hazard Identification...", "score": 0.847, "chunk_index": 2},
    ...
  ],
  "sources": ["Knowledge graph: 3 facts", "Document search: 5 passages"]
}
```

The response includes both the synthesised answer and the raw retrieval evidence (`kg_facts`, `vector_chunks`, `kg_sparql`). The Fiori UI uses these to show the user exactly where the answer came from — which SPARQL query retrieved the structured facts, and which document passages supported the narrative answer.

---

## 7.9 Conversation history

The `/query` endpoint accepts a `history` list in the request body. This is how multi-turn conversations work without server-side session state.

```python
# First question — no history
POST /query
{"question": "What are the hazard codes for acetone?", "material_number": "ACE001", "history": []}

# Second question — pass previous turn
POST /query
{
  "question": "And what PPE should I wear when handling it?",
  "material_number": "ACE001",
  "history": [
    {"role": "user",      "content": "What are the hazard codes for acetone?"},
    {"role": "assistant", "content": "The GHS hazard codes are H225, H319, and H336."}
  ]
}
```

The answer node in the LangGraph graph includes the history in its prompt, so the second question gets a contextually aware answer ("Given the flammability hazard H225 that we discussed, you should wear...") without any server-side state.

The frontend keeps a rolling window of the last 10 messages — enough for conversational context without ballooning the prompt. Older messages are silently dropped.

---

## 7.10 Testing: three scenarios that prove hybrid wins

The following three test cases demonstrate why hybrid retrieval is better than either strategy alone. Run them after uploading the acetone MSDS to both stores.

### 7.10.1 The KG wins: precise structured facts

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the GHS hazard codes for acetone?",
    "material_number": "ACE001",
    "history": []
  }'
```

Expected KG answer:
```
H225, H319, H336
```

Expected vector answer (typical):
```
Acetone is classified under several GHS hazard categories. The safety data
sheet indicates it is a highly flammable substance with eye irritation
properties. Refer to Section 2 for complete hazard identification...
```

The KG returns the exact codes. The vector chain returns useful prose but buries the codes in a paragraph. The synthesised answer leads with the codes and adds the prose context.

### 7.10.2 The vector wins: narrative safety procedures

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What first aid should I give if someone inhales acetone vapour?",
    "material_number": "ACE001",
    "history": []
  }'
```

The KG stores structured facts — hazard codes, exposure limits, precaution flags. It does not store the detailed first-aid procedure paragraph. The vector chain retrieves the exact passage from Section 4 of the MSDS. The final answer comes primarily from the vector chain here, with the KG contributing the exposure limit for context.

### 7.10.3 Both contribute: a complex combined question

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Is acetone classified as a flammable liquid and what precautions should I take when storing it?",
    "material_number": "ACE001",
    "history": []
  }'
```

The KG answers the first part precisely: H225 confirms flammable liquid classification. The vector chain answers the second part: storage precautions from Section 7 of the MSDS. Neither could answer both parts alone. The synthesis LLM combines them into a single coherent answer.

---

## 7.11 Monitoring chain performance

Add timing instrumentation to the orchestrator to track which chain is the bottleneck:

```python
import time

with ThreadPoolExecutor(max_workers=2) as executor:
    start = time.time()
    futures = {executor.submit(fn, state): name for name, fn in chains.items()}
    for future in as_completed(futures, timeout=35):
        name = futures[future]
        elapsed = time.time() - start
        logger.info("%s chain completed in %.2fs", name, elapsed)
        results[name] = future.result(timeout=30)

total = time.time() - start
logger.info("Both chains completed in %.2fs (wall clock)", total)
```

In a typical run against a populated HANA instance:

```
INFO: vector chain completed in 1.83s
INFO: kg chain completed in 2.41s
INFO: Both chains completed in 2.41s (wall clock)
```

The wall-clock time is the slower chain, not the sum. If you ran these sequentially, the same run would take 4.24 seconds. The parallel design saves ~1.8 seconds on every query.

---

## 7.12 Summary

In this chapter we built the core of the hybrid RAG system:

- Defined a shared **`HybridRAGState`** TypedDict that all components read and write
- Built the **vector chain**: embed question → cosine search HANA → summarise with Gemini
- Built the **KG chain**: generate SPARQL → execute on HANA → retry-on-empty → summarise
- Wrote the **merge function**: synthesise when both chains return results; fall back gracefully when one or neither does
- Assembled the **orchestrator** using `ThreadPoolExecutor` for true parallel execution
- Exposed a **`/query` endpoint** with input validation and a clean request/response contract
- Demonstrated **stateless conversation history** passed in every request
- Verified with **three test scenarios** that hybrid retrieval outperforms either strategy alone

The parallel orchestrator is the most important design decision in this system. Everything built in Chapters 3, 4, 5, and 6 converges here.

---

## 7.13 Checkpoint

Before continuing to Chapter 8, verify the following:

```bash
# 1. Both chains import without errors
cd agents
python -c "from agents.vector_chain import run_vector_chain; print('vector OK')"
python -c "from agents.kg_chain import run_kg_chain; print('kg OK')"

# 2. The orchestrator runs (requires HANA connection and Vertex AI)
python -c "
from agents.orchestrator import run_hybrid_rag
result = run_hybrid_rag({
    'question': 'What are the hazard codes?',
    'material_number': 'ACE001',
    'history': [],
    'vector_answer': '', 'vector_chunks': [],
    'kg_answer': '', 'kg_sparql': '', 'kg_facts': [],
    'final_answer': '', 'sources': [], 'error': None,
})
print('answer:', result.get('final_answer', '')[:80])
"

# 3. The /query endpoint responds
uvicorn main:app --port 8000 &
curl -s -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is acetone?","material_number":"ACE001","history":[]}' \
  | python -m json.tool
```

If all three commands succeed and the final curl returns a JSON response with an `answer` field, the hybrid RAG agent is working. Chapter 8 extends it with a multi-agent supervisor layer for complex, multi-domain queries.

---

*End of Chapter 7*
