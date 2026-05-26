"""
agents/srv/vector_srv.py

Vector store service for SAP HANA Cloud REAL_VECTOR columns.

Exposes:
  store_embedding(material_number, chunk_text, chunk_index, embedding)
  search_similar(question, material_number, top_k) -> list[dict]
  delete_vectors(material_number) -> int
  count_vectors(material_number) -> int

The table is created lazily on first insert — dimension is read from the
first embedding response so no hardcoded 768 lives in application code.
"""
from .hdb_srv import get_connection
from .vertex_srv import embed_text

TABLE_NAME = "MSDS_VECTORS"
_table_created = False


def _ensure_table(embedding_dim: int):
    """Create MSDS_VECTORS if it does not exist. Runs at most once per process."""
    global _table_created
    if _table_created:
        return
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            ID BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            MATERIAL_NUMBER NVARCHAR(100) NOT NULL,
            CHUNK_TEXT NCLOB NOT NULL,
            CHUNK_INDEX INTEGER NOT NULL,
            EMBEDDING REAL_VECTOR({embedding_dim})
        )
    """)
    conn.commit()
    cursor.close()
    _table_created = True


def store_embedding(
    material_number: str,
    chunk_text: str,
    chunk_index: int,
    embedding: list[float],
) -> None:
    """Store a single chunk and its embedding vector."""
    _ensure_table(len(embedding))
    conn = get_connection()
    cursor = conn.cursor()
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    cursor.execute(f"""
        INSERT INTO {TABLE_NAME} (MATERIAL_NUMBER, CHUNK_TEXT, CHUNK_INDEX, EMBEDDING)
        VALUES (?, ?, ?, TO_REAL_VECTOR(?))
    """, (material_number, chunk_text, chunk_index, embedding_str))
    conn.commit()
    cursor.close()


def upsert_vectors(
    conn,
    material_number: str,
    chunk_index: int,
    chunk_text: str,
    embedding: list[float],
) -> None:
    """
    UPSERT a chunk by (material_number, chunk_index).
    Re-uploading a document replaces existing rows cleanly.
    Accepts an explicit connection for thread-local callers (doc_srv).
    """
    _ensure_table(len(embedding))
    cursor = conn.cursor()
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    # HANA UPSERT: insert or update by primary-key equivalent composite
    cursor.execute(f"""
        UPSERT {TABLE_NAME} (MATERIAL_NUMBER, CHUNK_INDEX, CHUNK_TEXT, EMBEDDING)
        VALUES (?, ?, ?, TO_REAL_VECTOR(?))
        WITH PRIMARY KEY
    """, (material_number, chunk_index, chunk_text, embedding_str))
    conn.commit()
    cursor.close()


def search_similar(
    question: str,
    material_number: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Embed the question and return the top-k most similar chunks for a material.
    Returns a list of dicts: {chunk, chunk_index, score}.
    """
    question_embedding = embed_text(question)
    embedding_str = "[" + ",".join(str(x) for x in question_embedding) + "]"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT TOP {top_k}
            CHUNK_TEXT,
            CHUNK_INDEX,
            COSINE_SIMILARITY(EMBEDDING, TO_REAL_VECTOR(?)) AS SCORE
        FROM {TABLE_NAME}
        WHERE MATERIAL_NUMBER = ?
        ORDER BY SCORE DESC
    """, (embedding_str, material_number))
    rows = cursor.fetchall()
    cursor.close()
    return [
        {"chunk": row[0], "chunk_index": row[1], "score": float(row[2])}
        for row in rows
    ]


def delete_vectors(material_number: str) -> int:
    """Delete all vectors for a material. Returns the number of rows deleted."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"DELETE FROM {TABLE_NAME} WHERE MATERIAL_NUMBER = ?",
        (material_number,),
    )
    deleted = cursor.rowcount
    conn.commit()
    cursor.close()
    return deleted


def count_vectors(material_number: str) -> int:
    """Return the number of stored vectors for a material."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE MATERIAL_NUMBER = ?",
        (material_number,),
    )
    row = cursor.fetchone()
    cursor.close()
    return row[0] if row else 0
