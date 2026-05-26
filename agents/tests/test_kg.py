"""
agents/tests/test_kg.py

End-to-end test for the knowledge graph pipeline.

Tests:
  1. Extract triples from hand-written MSDS text via Gemini
  2. Store triples in HANA named graph
  3. Count stored triples
  4. Query for GHS hazard codes → expect H225, H319, H336
  5. Query for exposure limits → expect values with ppm unit

Run from agents/ directory:
  python tests/test_kg.py

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
from srv.kg_srv import extract_triples, store_triples, query_graph, count_triples

load_dotenv()

TEST_MATERIAL = "ACETONE-TEST-001"
TEST_TEXT = """
Section 2: Hazard Identification
GHS Classification: Flammable Liquid Category 2 (H225), Eye Irritation Category 2A (H319),
Specific Target Organ Toxicity (Single Exposure) Category 3 (H336).

Section 8: Exposure Controls
OSHA PEL: 1000 ppm TWA. ACGIH TLV: 500 ppm TWA, 750 ppm STEL.

Section 7: Handling and Storage
Keep away from heat, sparks, and open flames. Use explosion-proof equipment.
Wear chemical-resistant gloves and safety goggles. Ensure adequate ventilation.

Supplier: Sigma-Aldrich, 3050 Spruce Street, St. Louis, MO 63103
"""

print("Extracting triples from MSDS text...")
triples = extract_triples(TEST_TEXT, TEST_MATERIAL)
print(f"Extracted {len(triples)} triples:")
for t in triples:
    print(f"  {t['predicate']}: {t['object']}")

print(f"\nStoring triples in HANA named graph...")
stored = store_triples(TEST_MATERIAL, triples)
print(f"Stored {stored} triples")

total = count_triples(TEST_MATERIAL)
print(f"Total triples in graph: {total}")

print("\nQuerying: 'What are the GHS hazard codes for this material?'")
result = query_graph(TEST_MATERIAL, "What are the GHS hazard codes for this material?")
print(f"SPARQL generated:\n{result['sparql']}")
print(f"Facts found: {result['facts']}")

assert len(result["facts"]) > 0, "Expected at least one hazard code"
print("  -> Hazard codes found: OK")

print("\nQuerying: 'What is the exposure limit?'")
result = query_graph(TEST_MATERIAL, "What is the occupational exposure limit?")
print(f"Facts found: {result['facts']}")

assert len(result["facts"]) > 0, "Expected at least one exposure limit"
print("  -> Exposure limits found: OK")

print("\nKnowledge graph test: OK")
