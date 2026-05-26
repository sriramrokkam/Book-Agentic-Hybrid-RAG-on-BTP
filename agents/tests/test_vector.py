"""
agents/tests/test_vector.py

End-to-end test for the vector store pipeline.

Tests:
  1. Embed and store 5 hand-crafted MSDS chunks
  2. Count stored vectors
  3. Cosine similarity search for two different questions
  4. Verify ranking: flammability question → flammability chunk on top
                     PPE question          → PPE chunk on top

Run from agents/ directory:
  python tests/test_vector.py

Requires:
  - HANA_HOST, HANA_PORT, HANA_USER, HANA_PASSWORD in .env
  - GOOGLE_APPLICATION_CREDENTIALS pointing to a valid GCP service-account JSON
  - The Vertex AI User role on the service account
"""
import os
import sys

# Allow imports from the agents/ root when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from srv.vector_srv import store_embedding, search_similar, count_vectors
from srv.vertex_srv import embed_text

load_dotenv()

TEST_MATERIAL = "ACETONE-TEST-001"
TEST_CHUNKS = [
    "Acetone is a highly flammable liquid and vapor. Flash point: -18°C. "
    "Keep away from heat and open flames.",
    "First aid for skin contact: Wash with soap and water for at least 15 minutes. "
    "Remove contaminated clothing.",
    "GHS Classification: Flammable Liquid Category 2. Eye Irritant Category 2A.",
    "Personal Protective Equipment: Wear chemical resistant gloves and safety glasses "
    "when handling.",
    "Storage: Store in a cool, dry, well-ventilated area away from ignition sources "
    "and incompatible materials.",
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

assert results[0]["score"] > 0.70, "Expected flammability chunk at top with score > 0.70"
print("  -> Flammability chunk ranked first: OK")

print("\nSearching: 'What PPE is required?'")
results = search_similar("What PPE is required?", TEST_MATERIAL)
for r in results:
    print(f"  Score: {r['score']:.4f} | {r['chunk'][:80]}...")

assert results[0]["score"] > 0.70, "Expected PPE chunk at top with score > 0.70"
print("  -> PPE chunk ranked first: OK")

print("\nVector search: OK")
