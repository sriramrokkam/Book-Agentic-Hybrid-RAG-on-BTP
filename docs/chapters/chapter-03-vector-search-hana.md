# Chapter 3: Vector Search on SAP HANA Cloud

When a safety officer asks "What precautions are needed when handling this chemical?", they are asking a semantic question. The answer might be phrased differently in different sections of the PDF — Section 7 calls it "handling requirements", Section 8 describes it under "exposure controls", and Section 15 restates it as a regulatory obligation. Vector search finds it by meaning, not by exact keyword match — this is what makes it superior to SAP's built-in DMS full-text search for narrative document content.

The same applies to every document type the Material Document Intelligence Platform handles. An invoice might describe payment terms in a header note or in a line-item annotation. A batch certificate might record a test result in a summary table or in a methodology paragraph. Vector search surfaces the right passage regardless of where in the document it appears.

By the end of this chapter you will have a working vector search system on HANA Cloud. You will take a chunk of text from a material document, turn it into a 768-dimensional vector using Google's `text-embedding-004` model, store it in a `REAL_VECTOR` column, and retrieve the most semantically similar chunks for a natural language question — all in roughly 200 lines of Python.

The closing section of this chapter is equally important: an honest account of what vector search cannot do. That limitation is the precise motivation for Chapter 4, where we add a knowledge graph to handle the queries that vectors get wrong.

---

## 3.1 What Are Embeddings? Intuition Without the Math

If you have spent your career writing ABAP, CDS views, and OData services, the word "embedding" probably sounds like something invented to make you feel old. It isn't. The idea is older than most enterprise software, and the intuition is simple.

An embedding is a fixed-length list of numbers — in our case, 768 floating-point numbers — that represents the *meaning* of a piece of text. The crucial property is this: two pieces of text with similar meanings produce embeddings that are close to each other in 768-dimensional space. Two pieces of text with different meanings produce embeddings that are far apart.

A useful analogy: imagine you are sorting books in a library. A traditional database would file them by title (alphabetical order) or by author. That is exact-match retrieval — fast, but useless if you don't know the title. A librarian, by contrast, knows that *Crime and Punishment* and *The Brothers Karamazov* belong on the same shelf because they are both Dostoevsky novels about guilt and redemption. The librarian has put each book at a *position* that reflects its content. Books on similar topics end up close together.

Embeddings do the same thing for text, but in 768 dimensions instead of two. The "position" of a sentence is just its embedding vector. Sentences about flammability cluster together. Sentences about first aid cluster together. Sentences about regulatory codes cluster together — and importantly, they cluster *separately* from the flammability sentences, even when they mention the same chemical.

> **Note:** The number 768 is not magic. It is simply the output dimension chosen by the team that trained `text-embedding-004`. Other models produce 384, 1024, 1536, or 3072 dimensions. Higher is not always better — it just means more storage and slower comparisons. For our use case, 768 is a comfortable balance.

Two further points before we move on.

First, embeddings are not human-readable. If you print one out, you will see something like `[0.0234, -0.1107, 0.0891, ..., 0.0023]`. The individual numbers mean nothing in isolation. Their meaning emerges only in *relation* to other embeddings — specifically, in how close or far apart they are.

Second, the model that produces embeddings is the same model (or a sibling model) that was trained on huge corpora of text. It has internalized which words and phrases tend to occur in similar contexts, and it projects each input into a position that reflects that learned structure. You don't train the model. You don't fine-tune it. You just call it as an API.

Calling the API gives you a vector. Storing that vector and searching across millions of them efficiently is the database's job. Until recently, that meant using a specialized vector database — Pinecone, Weaviate, Milvus — alongside your real database. As of HANA Cloud QRC 1/2024, you no longer need a sidecar. HANA does it natively, and that is the next topic.

---

## 3.2 The HANA Cloud REAL_VECTOR Column Type

HANA has always been a column-store database optimized for analytical workloads. In 2024, SAP added a new native column type built specifically for AI: `REAL_VECTOR`.

A `REAL_VECTOR` column stores a fixed-dimension array of single-precision floats. When you declare the column you fix the dimension (for example, `REAL_VECTOR(768)`), and HANA refuses any insert with a different dimension. This is what you want — mixing dimensions in the same column would mean comparing apples to oranges.

What makes this more than a glorified `BLOB` column is the set of operators HANA exposes on it:

- `TO_REAL_VECTOR(string)` — converts a string in the form `'[0.1, 0.2, ..., 0.768]'` into a real vector value. This is how you bind a parameter from Python.
- `COSINE_SIMILARITY(v1, v2)` — returns the cosine of the angle between two vectors. Range: `-1.0` (opposite) to `+1.0` (identical direction). For unit-normalized embeddings (which `text-embedding-004` produces), this is in practice between `0.0` and `1.0`.
- `L2DISTANCE(v1, v2)` — Euclidean distance between two vectors. Useful when your model is not normalized.

These operators are SIMD-accelerated on the HANA engine, which means a single CPU instruction processes multiple floats in parallel. Searching across hundreds of thousands of 768-dimensional vectors takes milliseconds, not seconds.

> **Tip:** For embeddings produced by Google, OpenAI, and Cohere — all of which are L2-normalized at the API boundary — `COSINE_SIMILARITY` is the right choice. Use `L2DISTANCE` only if you are working with embeddings that are not normalized.

A second feature worth knowing about (we will not use it in this chapter, but it matters at scale) is the **HNSW index**. Without an index, every similarity query scans the entire table. With an HNSW index, HANA builds a graph structure that gets you approximate-nearest-neighbor results in logarithmic time. For our chapter you will not need it — five document chunks search in under 10 ms — but for production deployments with millions of chunks, indexing is essential. We come back to this in Chapter 10 when we tune for production.

![HANA Cloud Central](docs/screenshots/hana/04-hana-central.png)
*Figure: SAP HANA Cloud Central — the REAL_VECTOR column type is available in all HANA Cloud instances from version 4.0 onwards*

![Vector Embedding Pipeline](docs/screenshots/diagrams/04-vector-pipeline.png)

*Figure 3.1 — The vector pipeline has two phases. Ingestion (top): PDF text is chunked, each chunk is sent to `text-embedding-004`, and the resulting 768-dimensional vector is written to `MSDS_VECTORS`. Query time (bottom): the question is embedded with the same model, then HANA computes cosine distance between the query vector and every stored vector, returning the top-k most relevant chunks.*

---

## 3.3 Creating the Vector Table: The Lazy Initialization Pattern

We need a table to hold our embeddings. The schema is simple:

```sql
CREATE TABLE MSDS_VECTORS (
    ID BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    MATERIAL_NUMBER NVARCHAR(100) NOT NULL,
    CHUNK_TEXT NCLOB NOT NULL,
    CHUNK_INDEX INTEGER NOT NULL,
    EMBEDDING REAL_VECTOR(768)
);
```

> **About the table name:** The table is named MSDS_VECTORS because the reference implementation was first built for MSDS documents. In a multi-document-type deployment, you would use DOCUMENT_VECTORS with an additional DOC_TYPE column, or a separate table per type. The core SQL pattern — REAL_VECTOR column, COSINE_SIMILARITY search, MATERIAL_NUMBER filter — is identical regardless of document type.

`MATERIAL_NUMBER` is the SAP material identifier — the same Material Number you would look up in SAP MM via transaction MM03. In the Material Document Intelligence Platform, the CAP service layer validates this value against real S/4HANA product master data via API_PRODUCT_SRV before accepting any document upload. This ensures that vectors are always anchored to a legitimate, active SAP material — not a free-text label that could drift out of sync with the product master. We use it as the tenant key so we can search within a single material's chunks. `CHUNK_TEXT` is the raw text of the chunk; `CHUNK_INDEX` lets us reconstruct order if we need to. `EMBEDDING` is the 768-dimensional vector we computed from `CHUNK_TEXT`.

You could just run this `CREATE TABLE` statement once with the SAP HANA Database Explorer and be done with it. But there is a subtle reason not to.

The dimension `768` is hardcoded into the schema. If at any point you decide to switch from `text-embedding-004` (768 dim) to a model with a different output dimension, your insert will fail and you will need to drop and recreate the table. Worse, that hardcoded number lives in your DDL while the actual dimension lives in the model — two sources of truth that can drift apart.

The cleaner pattern is **lazy initialization**: don't create the table until the first time you embed something, then read the dimension from the embedding response and use it in the `CREATE TABLE`. This way your code has exactly one source of truth — the model's actual output dimension at runtime.

Here is the relevant snippet from `agents/srv/vector_srv.py` (we will see the full file in section 3.8):

```python
TABLE_NAME = "MSDS_VECTORS"
_table_created = False

def _ensure_table(embedding_dim: int):
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
```

Three things to note:

1. The `_table_created` module-level flag is a one-time guard. We don't want to issue `CREATE TABLE IF NOT EXISTS` on every insert — that is a roundtrip we don't need.
2. The `IF NOT EXISTS` clause means restarting the Python process is safe. The first call after restart will hit the database once, see the table exists, and move on.
3. The `embedding_dim` is passed in by the caller, who got it from the actual embedding. There is no hardcoded `768` anywhere in the application code.

> **Warning:** Do not be tempted to add an `ALTER TABLE` path that resizes the `REAL_VECTOR` column if the dimension changes. A dimension change means your old embeddings are incompatible with new ones, and you should treat it as a full re-indexing event — drop the table, re-embed all your documents, and reload. Silently mixing dimensions is a recipe for confusion.

---

## 3.4 Calling text-embedding-004 from Python

We talked about embeddings as a concept; now we need to actually produce one. The `langchain_google_genai` library gives us a clean interface to Google's embedding models without the operational complexity of a dedicated Vertex AI SDK setup.

Looking at `agents/srv/vertex_srv.py`:

```python
import os
import threading
import vertexai
from vertexai.generative_models import GenerativeModel
from vertexai.language_models import TextEmbeddingModel
from dotenv import load_dotenv

load_dotenv()

_init_lock = threading.Lock()
_initialized = False

def _ensure_initialized():
    global _initialized
    if not _initialized:
        with _init_lock:
            if not _initialized:
                vertexai.init(
                    project=os.getenv("GCP_PROJECT_ID"),
                    location=os.getenv("GCP_LOCATION", "us-central1")
                )
                _initialized = True

def get_llm():
    _ensure_initialized()
    return GenerativeModel("gemini-2.5-flash-preview-05-20")

def get_embedding_model():
    _ensure_initialized()
    return TextEmbeddingModel.from_pretrained("text-embedding-004")

def embed_text(text: str) -> list[float]:
    model = get_embedding_model()
    embeddings = model.get_embeddings([text])
    return embeddings[0].values  # list of 768 floats
```

The pattern here mirrors the lazy table creation pattern. `vertexai.init()` is global SDK state; calling it more than once is wasteful. The double-checked locking idiom (`if not _initialized` outside the lock, then again inside) is the standard way to do this safely under FastAPI's threaded request model. If you have never seen the pattern before, the gist is: the outer check is the fast path for the common case (already initialized, no lock needed), and the inner check makes sure that two threads racing for the lock don't both initialize.

`get_embedding_model()` returns a `TextEmbeddingModel` instance bound to `text-embedding-004`. This is cheap — the SDK caches the model client internally — but we still gate it behind `_ensure_initialized` so that calling code does not have to think about ordering.

`embed_text()` is the function the rest of our application uses. It takes a string and returns a Python list of 768 floats. Internally, the SDK takes a list of strings, so we pass `[text]` and unwrap the first result with `embeddings[0].values`.

> **Note:** Vertex AI's embedding endpoint accepts batches of up to 250 texts per call. For a one-off document upload that ends up with maybe 30 chunks, the savings of batching are negligible compared to the simplicity of one-text-per-call. We will revisit batching in Chapter 10 when we look at bulk-loading historical documents.

You should also be aware that Vertex AI charges per 1,000 input characters for embeddings (about $0.000025 per 1,000 chars at the time of writing). A typical 12-page MSDS PDF has roughly 30,000 characters and chunks into ~30 pieces. The cost to embed it is approximately $0.0008 — less than a tenth of a cent. Search-time embeddings (one per question) are equally cheap.

---

## 3.5 Storing Embeddings: INSERT with REAL_VECTOR

Once we have an embedding (a Python `list[float]`), we need to get it into the `REAL_VECTOR` column. The HANA Python driver `hdbcli` does not yet have a native binding for vector parameters, so we use the `TO_REAL_VECTOR(string)` SQL function with a string parameter.

The format HANA expects is a JSON-style array literal: `[0.0234, -0.1107, 0.0891, ...]`. We build this string in Python with a simple comma-join:

```python
embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
```

A typical 768-dimensional embedding string is around 12,000 characters. That is fine — HANA accepts it as an `NVARCHAR` parameter without issue.

The full insert function:

```python
def store_embedding(material_number: str, chunk_text: str, chunk_index: int, embedding: list[float]):
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
```

A few engineering notes:

- We pass `material_number`, `chunk_text`, `chunk_index`, and the embedding string as positional parameters. This is parameterized SQL — no concatenation of user data into the query, so SQL injection is impossible.
- `_ensure_table(len(embedding))` runs on every call but exits early after the first invocation thanks to the `_table_created` flag.
- We commit per insert. For uploading a single document this is fine. For bulk uploads, batch your inserts and commit once at the end — Chapter 10 covers this.

> **Tip:** If you want to verify what got stored, the SAP HANA Database Explorer is your friend. Open the `MSDS_VECTORS` table, click "Open Data", and you will see your rows. The `EMBEDDING` column displays as a truncated array preview, but you can click into a cell to see the full 768 values.

> **Note:** You can inspect the MSDS_VECTORS table in SAP HANA Database Explorer (accessible from HANA Cloud Central → Open in → SAP HANA Database Explorer). The EMBEDDING column will show truncated vector data like `[0.0234, -0.1823, 0.0912, ...]`.

---

## 3.6 Cosine Similarity Search: The Query Explained

This is the heart of the chapter. The query that retrieves the top-K chunks for a question is:

```sql
SELECT TOP 5
    CHUNK_TEXT,
    CHUNK_INDEX,
    COSINE_SIMILARITY(EMBEDDING, TO_REAL_VECTOR(?)) AS SCORE
FROM MSDS_VECTORS
WHERE MATERIAL_NUMBER = ?
ORDER BY SCORE DESC;
```

Five clauses, each doing real work. Let's read them in execution order.

**`WHERE MATERIAL_NUMBER = ?`** filters the table to chunks belonging to a specific material. Without this, our search would compete across every chunk of every document in the table — fine when you have one document, fatal when you have ten thousand. By filtering early, HANA scans only the rows that could possibly match. This is the one place in the query where the optimizer can use a B-tree index, so make sure you have one on `MATERIAL_NUMBER` once you go to production. (We add it in Chapter 10.)

**`COSINE_SIMILARITY(EMBEDDING, TO_REAL_VECTOR(?))`** is the per-row computation. For each row passing the `WHERE` filter, HANA takes the stored `EMBEDDING` vector, the question's vector (parsed from the bound parameter), and computes the cosine of the angle between them. The result is a `DOUBLE` between roughly 0.0 and 1.0 — higher means more similar. This is where the SIMD acceleration earns its keep.

**`AS SCORE`** names the result so we can refer to it in the `ORDER BY` clause. It's a small thing but worth noting because it is what allows us to write `ORDER BY SCORE DESC` instead of having to repeat the `COSINE_SIMILARITY(...)` expression.

**`ORDER BY SCORE DESC`** sorts the surviving rows from highest similarity to lowest. The bulk of the cost here is the sort itself; for our small data this is instant.

**`SELECT TOP 5`** returns only the first five rows after the sort. In LangGraph's vector chain we will pass these chunks to the LLM as context for answering the question. Five is a reasonable default — large enough to give the model useful coverage, small enough not to blow the context window.

The order of operations matters. HANA's optimizer is smart enough to push the `WHERE` filter down to the table scan (so we never compute similarity for chunks belonging to other materials), but you should still write your queries with the filter explicit. Don't compute similarity across the whole table and filter the result.

> **Important:** A common mistake is to forget the `WHERE` clause when prototyping with one material, then keep that habit when you add a second. Every query in your application should filter by `MATERIAL_NUMBER`. There is no business reason a question about one material should ever surface a chunk from a different material's document, even if some words happen to overlap.

The Python wrapper:

```python
def search_similar(question: str, material_number: str, top_k: int = 5) -> list[dict]:
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
    return [{"chunk": row[0], "chunk_index": row[1], "score": float(row[2])} for row in rows]
```

We embed the question (one Vertex AI call), build the parameter string the same way as for inserts, and run the query. The result is a list of dicts — the chunk text, its position in the original document, and its similarity score.

> **Note:** `top_k` is interpolated into the SQL string, not bound as a parameter. This is safe because we control the value (it is a function argument with a default of 5, never user input). HANA does not allow `TOP ?` with bound parameters, so we have no choice. If you ever expose `top_k` to end users, validate it as an integer before interpolation.

---

## 3.7 Chunking Strategy for Material Documents

We have skipped over the most consequential design decision in any RAG system: how do you split a document into chunks?

Chunking is necessary because a 12-page MSDS does not fit usefully into a single embedding. Even if it did, retrieval would always return "the whole document" and the LLM would have to do all the work of finding the relevant sentence. Chunking lets us push the relevance work into the database.

The trade-off is fundamental:

- **Smaller chunks** (a sentence each) give precise retrieval — when the model returns chunk 47, you know exactly which sentence it cared about. But you lose context. A sentence like "It must be stored away from this material" is meaningless without the surrounding paragraph.
- **Larger chunks** (a full page) preserve context but introduce noise. A paragraph about flammability that also mentions "appropriate PPE" might score highly for a PPE question even though the actual PPE answer is on a different page.

The right chunking strategy adapts to document structure. Different document types that flow through the Material Document Intelligence Platform have different natural boundaries.

For **MSDS documents**, the OSHA 16-section format provides the primary boundary. Section 4 is always First Aid. Section 7 is always Handling and Storage. Section 8 is always Exposure Controls and PPE. These sections are typically 100–300 words — exactly the right size. We use OSHA section headers as the primary split point.

For **invoices**, the natural boundary is the line item block — each item group (description, quantity, unit price, total) forms one chunk. Header data (vendor, PO reference, payment terms) becomes its own chunk.

For **batch certificates**, the natural boundary is the test result section — each analytical parameter and its pass/fail result becomes a chunk. Summary sections and methodology notes are separate chunks.

For **maintenance manuals**, procedure steps are the natural boundary — each numbered step with its safety caution and tooling note stays together as a chunk.

The chunking approach adapts to document structure. The vector storage and retrieval code — `MSDS_VECTORS`, `store_embedding`, `search_similar` — does not change. The same HANA SQL runs identically regardless of whether the chunk came from an MSDS flammability section or an invoice payment terms block.

Our chunking rule for MSDS documents, which we will implement in Chapter 5 when we build `doc_srv.py`:

1. **Primary boundary:** OSHA section header. Each numbered section becomes one chunk.
2. **Secondary boundary:** if a section exceeds ~500 tokens, split on the next paragraph boundary inside it.
3. **Overlap:** each chunk shares ~50 tokens with the preceding chunk. This keeps a sentence from being orphaned at the boundary — if the relevant sentence happens to be the first one of a chunk, the prior chunk also contains it as context.

Token-wise, our targets are:

- Minimum chunk size: ~100 tokens (anything smaller loses context)
- Maximum chunk size: ~500 tokens (anything larger gets noisy)
- Overlap: ~50 tokens

> **Tip:** Tokens, not characters. A token is roughly 4 characters of English text or about 0.75 of a word. `text-embedding-004` accepts up to 2,048 tokens per embedding call, so we have plenty of headroom — 500 tokens is well under the limit.

For the test in this chapter we hand-write five short chunks that look like real document sentences. The full document chunker arrives in Chapter 5. The point of the test is to validate the round-trip: embed → store → embed-question → search → score.

---

## 3.8 Building vector_srv.py — The Vector Service Layer

Now we put the pieces together. Create the file `agents/srv/vector_srv.py` with the following content:

```python
import json
from .hdb_srv import get_connection
from .vertex_srv import embed_text

TABLE_NAME = "MSDS_VECTORS"
_table_created = False

def _ensure_table(embedding_dim: int):
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

def store_embedding(material_number: str, chunk_text: str, chunk_index: int, embedding: list[float]):
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

def search_similar(question: str, material_number: str, top_k: int = 5) -> list[dict]:
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
    return [{"chunk": row[0], "chunk_index": row[1], "score": float(row[2])} for row in rows]

def delete_vectors(material_number: str) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM {TABLE_NAME} WHERE MATERIAL_NUMBER = ?", (material_number,))
    deleted = cursor.rowcount
    conn.commit()
    cursor.close()
    return deleted

def count_vectors(material_number: str) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE MATERIAL_NUMBER = ?", (material_number,))
    row = cursor.fetchone()
    cursor.close()
    return row[0] if row else 0
```

The module exposes four functions to the rest of the application:

- `store_embedding(material_number, chunk_text, chunk_index, embedding)` — stores a single chunk and its vector. Called once per chunk during document upload.
- `search_similar(question, material_number, top_k)` — embeds the question and returns the top-K most similar chunks for a given material. Called once per user question.
- `delete_vectors(material_number)` — wipes a material's vectors. Called when a document is replaced or deleted. Returns the row count for logging.
- `count_vectors(material_number)` — reports how many chunks exist for a material. Useful for diagnostics and tests.

There is no `update_embedding` — for chunked documents, the right pattern is delete-then-reinsert. If you change the chunking algorithm, the chunk indices change, so partial updates are dangerous. Treat each upload as a fresh load.

> **Note:** The connection comes from `hdb_srv.py`, which uses thread-local storage to give each request thread its own HANA connection. `hdbcli` connections are not safe to share across threads, but they are cheap to create. Thread-locals give us per-thread reuse without any cross-thread contention. We covered this pattern briefly in Chapter 1 — the file is reproduced for completeness:

```python
import os
import threading
from hdbcli import dbapi
from dotenv import load_dotenv

load_dotenv()

_local = threading.local()

def get_connection():
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = dbapi.connect(
            address=os.getenv("HANA_HOST"),
            port=int(os.getenv("HANA_PORT", 443)),
            user=os.getenv("HANA_USER"),
            password=os.getenv("HANA_PASSWORD"),
            encrypt=True,
            sslValidateCertificate=False
        )
    return _local.conn
```

> **Warning:** `sslValidateCertificate=False` is fine for development against the BTP-issued HANA endpoint. For production you should provide the correct certificate via `sslTrustStore` and set `sslValidateCertificate=True`. We will tighten this in Chapter 9.

---

## 3.9 Testing: Business Questions Across Document Types

Time to see it work end-to-end. Create the file `agents/test_vector.py`:

```python
import os
from dotenv import load_dotenv
from srv.vector_srv import store_embedding, search_similar, count_vectors
from srv.vertex_srv import embed_text

load_dotenv()

TEST_MATERIAL = "ACETONE-TEST-001"
TEST_CHUNKS = [
    "Acetone is a highly flammable liquid and vapor. Flash point: -18°C. Keep away from heat and open flames.",
    "First aid for skin contact: Wash with soap and water for at least 15 minutes. Remove contaminated clothing.",
    "GHS Classification: Flammable Liquid Category 2. Eye Irritant Category 2A.",
    "Personal Protective Equipment: Wear chemical resistant gloves and safety glasses when handling.",
    "Storage: Store in a cool, dry, well-ventilated area away from ignition sources and incompatible materials."
]

print("Embedding and storing test chunks...")
for i, chunk in enumerate(TEST_CHUNKS):
    embedding = embed_text(chunk)
    store_embedding(TEST_MATERIAL, chunk, i, embedding)
    print(f"  Stored chunk {i}: dim={len(embedding)}, preview='{chunk[:50]}...'")

stored = count_vectors(TEST_MATERIAL)
print(f"\nStored {stored} vectors for material {TEST_MATERIAL}")

print("\nSearching: 'What precautions should I take near open flames?'")
results = search_similar("What precautions should I take near open flames?", TEST_MATERIAL)
for r in results:
    print(f"  Score: {r['score']:.4f} | {r['chunk'][:80]}...")

print("\nSearching: 'What PPE is required?'")
results = search_similar("What PPE is required?", TEST_MATERIAL)
for r in results:
    print(f"  Score: {r['score']:.4f} | {r['chunk'][:80]}...")
```

Run it from the `agents/` directory:

```bash
cd agents
python test_vector.py
```

Expected output (your numbers will vary slightly):

```
Embedding and storing test chunks...
  Stored chunk 0: dim=768, preview='Acetone is a highly flammable liquid and vapor. Fl...'
  Stored chunk 1: dim=768, preview='First aid for skin contact: Wash with soap and wat...'
  Stored chunk 2: dim=768, preview='GHS Classification: Flammable Liquid Category 2. E...'
  Stored chunk 3: dim=768, preview='Personal Protective Equipment: Wear chemical resis...'
  Stored chunk 4: dim=768, preview='Storage: Store in a cool, dry, well-ventilated are...'

Stored 5 vectors for material ACETONE-TEST-001

Searching: 'What precautions should I take near open flames?'
  Score: 0.8124 | Acetone is a highly flammable liquid and vapor. Flash point: -18°C. Keep aw...
  Score: 0.7456 | Storage: Store in a cool, dry, well-ventilated area away from ignition source...
  Score: 0.6203 | Personal Protective Equipment: Wear chemical resistant gloves and safety gla...
  Score: 0.5891 | GHS Classification: Flammable Liquid Category 2. Eye Irritant Category 2A...
  Score: 0.5102 | First aid for skin contact: Wash with soap and water for at least 15 minute...

Searching: 'What PPE is required?'
  Score: 0.8442 | Personal Protective Equipment: Wear chemical resistant gloves and safety gla...
  Score: 0.6334 | Storage: Store in a cool, dry, well-ventilated area away from ignition source...
  Score: 0.5912 | First aid for skin contact: Wash with soap and water for at least 15 minute...
  Score: 0.5108 | Acetone is a highly flammable liquid and vapor. Flash point: -18°C. Keep aw...
  Score: 0.4789 | GHS Classification: Flammable Liquid Category 2. Eye Irritant Category 2A...
```

This is exactly what you want to see. For the open-flames question, the flammability chunk wins at 0.81, with the storage chunk (which mentions "ignition sources") in second place at 0.74. The first-aid chunk, which has nothing to do with the question, ranks last at 0.51. For the PPE question, the actual PPE chunk wins decisively at 0.84.

```
# Expected terminal output:
Stored 3 chunks for material: acetone-test
Query 1: "What are the fire hazards of acetone?"
  Result 1 (score: 0.923): "Acetone is highly flammable..."
  Result 2 (score: 0.887): "Keep away from heat sources..."
Query 2: "What first aid is needed for skin contact?"
  Result 1 (score: 0.941): "Wash affected area with soap and water..."
  Result 2 (score: 0.812): "Remove contaminated clothing..."
Vector search: OK
```

Note the absolute scores. The top match for a well-targeted question lands around 0.80–0.85. This is the band where you should expect "good" semantic matches with `text-embedding-004`. Anything above 0.90 usually means near-paraphrase. Anything below 0.50 usually means the model is reaching.

The same vector infrastructure serves every document type without modification. A storage requirements question for an MSDS returns the Section 7 chunk. An approved quantity question for an invoice returns the line-item summary chunk. A viscosity test question for a batch certificate returns the test result chunk. The question changes. The search code does not. This is the commercial value of building on HANA's `REAL_VECTOR` column rather than on a document-type-specific text search engine.

> **Tip:** The scores are reproducible only if you re-embed identical text against the same model version. Vertex AI may update the model under the same name; if your scores drift over time, that is the most likely cause. Pin to a specific version if reproducibility matters.

If you see authentication errors at this point, double-check that `GOOGLE_APPLICATION_CREDENTIALS` points to your `gcp-sa-key.json` file and that the service account has the `Vertex AI User` role. The HANA side is more forgiving — connection errors usually surface as "host not reachable", which means a typo in `HANA_HOST` or a network rule blocking outbound 443.

---

## 3.10 What Vector Search Gets Right — and What It Gets Wrong

Time for honesty. Vector search is genuinely powerful, but it has a sharp limitation that becomes obvious as soon as you look at the third example.

Run the test one more time, with a precise factual question:

```python
print("\nSearching: 'What is the GHS hazard code for acetone?'")
results = search_similar("What is the GHS hazard code for acetone?", TEST_MATERIAL)
for r in results:
    print(f"  Score: {r['score']:.4f} | {r['chunk'][:80]}...")
```

You will see something like:

```
Searching: 'What is the GHS hazard code for acetone?'
  Score: 0.6534 | GHS Classification: Flammable Liquid Category 2. Eye Irritant Category 2A...
  Score: 0.5821 | Acetone is a highly flammable liquid and vapor. Flash point: -18°C. Keep aw...
  Score: 0.4912 | Storage: Store in a cool, dry, well-ventilated area away from ignition source...
  ...
```

The GHS classification chunk does come back first — at 0.65. That is a noticeably weaker score than the 0.81 we saw for flammability, despite this being a question about a chunk that literally contains the words "GHS Classification".

Why so weak? Because the question asks for a *code* — the H-statement code like "H225" — and our chunk does not contain "H225" verbatim. It contains "Flammable Liquid Category 2", which is the human-readable form. The embedding model knows these are related concepts, but it does not encode "H225 = Flammable Liquid Category 2" as a hard equality. It encodes them as *near-each-other-in-768-d-space*, which is fuzzier.

For our test data this still works because there are only five chunks and the GHS chunk is the closest. Now imagine the same query against a real corpus with 50 MSDSs and 1,500 chunks. Many chunks will mention "Category 2" in different contexts — fire protection regulations, transport classifications, industrial hygiene reports. The signal-to-noise ratio collapses. The right chunk might rank fourth or fifth, or might not appear in the top five at all.

This is **the GHS code problem**, and it is not a bug in vector search — it is the nature of vector search. Embeddings are wonderful for fuzzy semantic matching ("precautions near open flame" → "keep away from heat and ignition sources"). They are bad at exact symbolic recall ("H225" → the row whose `ghsCode` literal equals `"H225"`).

Three categories of question hit this limitation hard:

1. **Identifier lookups.** GHS codes (H225, H319), CAS numbers (67-64-1 for acetone), UN numbers (UN1090), product codes. Vector search treats these as fuzzy strings and competes them against every other alphanumeric token in your corpus.
2. **Aggregations and counts.** "How many of my materials have flash point below 0°C?" is impossible for vector search — there is no "count" embedding direction. You need structured query.
3. **Negation and exclusion.** "Show me MSDSs that do *not* require respiratory protection." Embeddings have no robust way to encode "not" — the embedding for "respiratory protection required" and "respiratory protection not required" is closer than you would hope.

SAP customers running on HANA have always thought in structured terms. Materials, hazard codes, GHS classifications, batch test results, invoice amounts — these are not free text. They are master data. They live in tables with foreign keys. They are the kind of thing a knowledge graph models naturally.

That is the bridge into Chapter 4. We will take the same material document, extract its structured facts into RDF triples, store them in HANA's graph engine, and query them with SPARQL. When the regulatory auditor asks "What is the GHS hazard classification for this chemical?", we will return "H225" with full confidence — not by guessing from a 0.65 cosine similarity, but by traversing a graph relationship that was set when the document was ingested.

The full Hybrid RAG agent in Chapter 7 runs both retrievers in parallel and lets a routing classifier decide which answer to trust. Vector search owns the fuzzy questions. The knowledge graph owns the precise ones. Neither is sufficient alone; together they cover the question space enterprise document users actually ask.

---

## 3.11 Summary

In this chapter you built a working vector search system on HANA Cloud. The major points to take away:

- **Embeddings are positions in 768-dimensional space.** Two pieces of text with similar meanings end up close together. The model learns this from large corpora and you call it as an API.
- **`REAL_VECTOR` is HANA's native vector column type.** It stores fixed-dimension float arrays and exposes SIMD-accelerated `COSINE_SIMILARITY` and `L2DISTANCE` operators. You do not need a separate vector database.
- **Lazy table initialization keeps your schema in sync with your model.** Read the dimension from the first embedding response and use it in `CREATE TABLE IF NOT EXISTS`. Never hardcode the dimension in DDL.
- **The cosine similarity query has five clauses, each load-bearing.** `WHERE` filters early, `COSINE_SIMILARITY` computes per-row, `AS SCORE` names the result, `ORDER BY SCORE DESC` sorts, `TOP K` truncates.
- **Chunking adapts to document structure; the storage code does not.** MSDS documents use OSHA section boundaries. Invoices use line-item blocks. Batch certificates use test result sections. The same `MSDS_VECTORS` table and `search_similar` function serve all document types.
- **The `MATERIAL_NUMBER` column is the anchor to SAP MM.** The CAP layer validates it against S/4HANA product master via API_PRODUCT_SRV before accepting uploads. Every vector in the table is traceable to a real, validated SAP material.
- **Vector search excels at fuzzy semantic matching and fails at precise symbolic recall.** The GHS code problem motivates the knowledge graph in Chapter 4.

The codebase now has working `hdb_srv.py`, `vertex_srv.py`, and `vector_srv.py` modules, plus a passing `test_vector.py` script. The vector retrieval half of the Hybrid RAG agent is live.

---

## 3.12 Checkpoint

Before moving on to Chapter 4, verify the following:

- [ ] `agents/srv/vector_srv.py` exists with the five functions: `_ensure_table`, `store_embedding`, `search_similar`, `delete_vectors`, `count_vectors`.
- [ ] Running `python test_vector.py` from the `agents/` directory prints five "Stored chunk" lines with `dim=768`.
- [ ] The test prints two search result blocks. The first ranks the flammability chunk at the top (~0.80). The second ranks the PPE chunk at the top (~0.84).
- [ ] Opening the `MSDS_VECTORS` table in the SAP HANA Database Explorer shows five rows for `MATERIAL_NUMBER = 'ACETONE-TEST-001'`.
- [ ] The third (optional) test — querying for "What is the GHS hazard code for acetone?" — returns the GHS chunk at the top, but with a noticeably lower score (~0.65). You understand why.

If all five items check out, you are ready for Chapter 4: **Knowledge Graph on HANA Cloud — RDF, SPARQL, and the Structured Half of RAG**. We will set up HANA's graph engine, load RDF triples extracted from the same material document, and query them with SPARQL — solving the GHS code problem in the most direct way possible.

If something is off, the most common issues at this stage are: missing or invalid Vertex AI credentials, incorrect HANA host/port, a service account without `Vertex AI User`, or the HANA instance being suspended (it sleeps after 3 days idle on trial accounts — restart it from the BTP cockpit). Fix and re-run `test_vector.py` until you see the expected output. The next chapter assumes a working `vector_srv.py`.
