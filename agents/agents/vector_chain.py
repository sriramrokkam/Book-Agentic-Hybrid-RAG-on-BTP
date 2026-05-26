"""
agents/agents/vector_chain.py
Book reference: Chapter 8 — The Parallel Hybrid RAG Agent

Vector retrieval chain (Chapter 8).

Steps:
  1. Embed the question via text-embedding-004
  2. Run cosine similarity search against MSDS_VECTORS in HANA Cloud
  3. Summarise the top-5 chunks with Gemini

Returns state updates: vector_answer, vector_chunks.
"""
import logging
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_core.messages import HumanMessage

from agents.state import HybridRAGState
from srv.hdb_srv import get_connection

logger = logging.getLogger(__name__)

_llm = None
_embedder = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-preview-05-20", temperature=0.1, max_tokens=1024)
    return _llm


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
    return _embedder


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
        embedding = _get_embedder().embed_query(question)
        embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

        # Step 2: Cosine search in HANA
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(COSINE_SEARCH_SQL, (embedding_str, material_number))
        rows = cursor.fetchall()
        cursor.close()

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

        response = _get_llm().invoke([HumanMessage(content=prompt)])
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
