# Book: Agentic Hybrid RAG on SAP BTP

## Project
Companion code repository for the book "Agentic Hybrid RAG on SAP BTP: A Hands-On Guide with LangGraph, HANA Cloud, and Google Vertex AI" by Sriram Rokkam.

GitHub: https://github.com/sriramrokkam/Book-Agentic-Hybrid-RAG-on-BTP

## What Is Here
- `agents/` — Python FastAPI + LangGraph agent (the working code)
- `cap-srv/` — CAP Node.js OData V4 service + Fiori Elements UI
- `joule/` — Joule A2A capability stub (see Appendix D)
- `docs/chapters/` — All 16 book chapters and appendices (Markdown)
- `docs/screenshots/` — BTP, HANA, GCP, architecture diagram screenshots
- `docs/CODE_MAP.md` — Chapter → file → function cross-reference
- `Agentic-Hybrid-RAG-on-SAP-BTP.pdf` — Compiled book PDF (295 pages)
- `book-header.tex` — LaTeX header for PDF generation (72 Brand + Source Code Pro)
- `MSDS_Ontology.ttl` — OWL ontology for knowledge graph

## Book Status (as of May 2026)
All 12 chapters and 4 appendices are written. PDF compiled at 295 pages.
Pending author input: Dedication, Foreword, Acknowledgements, About the Author (all in chapter-00).

## Reference Project
Real implementation lives at:
/Users/I310202/Library/CloudStorage/OneDrive-SAPSE/SR@Work/2026/99_Initiatives/911-Agentic-KG-RAG/
Use this for real code patterns — especially joule/, frontend/srv/, and backend/main.py (/a2a endpoint).

## PDF Generation
Requires: pandoc, xelatex, 72 Brand font, Source Code Pro font.
```bash
pandoc docs/chapters/chapter-*.md docs/chapters/appendix-*.md \
  -o Agentic-Hybrid-RAG-on-SAP-BTP.pdf \
  --pdf-engine=xelatex --syntax-highlighting=tango --toc \
  --include-in-header=book-header.tex \
  -V papersize=a4 -V fontsize=11pt \
  -M title="Agentic Hybrid RAG on SAP BTP" \
  -M author="Sriram Rokkam" -M date="May 2026"
```
Image paths in chapter files must be root-relative (docs/screenshots/...) not ../screenshots/.
The file gcp/02-gcp-new-project.png was corrupt (HTML file) — removed, needs retaking.

## Key Technical Decisions
- LangChain import: `langchain_google_genai` (NOT `langchain_google_vertexai` — deprecated)
- LLM instantiation: always lazy getters `_get_llm()`, never module-level
- Material number validation: `^[A-Za-z0-9_-]+$` at every entry point (SPARQL injection prevention)
- Named RDF graphs: `GRAPH <iri> { ... }` required — HANA returns empty silently without it
- Thread-local HANA connections via `threading.local()`
- CAP runs on :4004, FastAPI on :8000, communicate via BACKEND_URL env var

## Git / GitHub
- Remote: https://github.com/sriramrokkam/Book-Agentic-Hybrid-RAG-on-BTP.git
- Auth: sriramrokkam account (not NeXera-AI-Labs)
- Always commit and push after completing writing or build tasks

## Working Style
- Short responses, no trailing summaries
- Parallelize independent chapter writing using background agents
- Auto-commit and push after significant work units
