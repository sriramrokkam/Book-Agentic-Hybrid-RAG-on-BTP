# Front Matter
## Agentic Hybrid RAG on SAP BTP
### A Hands-On Guide with LangGraph, HANA Cloud, and Vertex AI 

---

## Title Page

**Agentic Hybrid RAG on SAP BTP**
*A Hands-On Guide with LangGraph, HANA Cloud, and Vertex AI*

Author: Sriram Rokkam

First Edition, 2026

---

## Copyright

Copyright © 2026 Sriram Rokkam. All rights reserved.

No part of this publication may be reproduced, distributed, or transmitted
in any form or by any means, including photocopying, recording, or other
electronic or mechanical methods, without the prior written permission of
the author, except in the case of brief quotations embodied in critical
reviews and certain other noncommercial uses permitted by copyright law.

The code samples in this book are released under the MIT License and are
freely available at:
https://github.com/sriramrokkam/book-agentic-hybrid-rag-on-btp

SAP, SAP BTP, SAP HANA, SAP CAP, and Joule are trademarks or registered
trademarks of SAP SE. Google Cloud, Vertex AI, and Gemini are trademarks
of Google LLC. All other trademarks are the property of their respective
owners. The author is not affiliated with SAP SE or Google LLC.

---


## Preface

I have spent years working at the intersection of SAP and cloud platforms,
watching enterprises struggle with the same problem in different forms: they
have extraordinary data — decades of business transactions, master data,
documents, and domain knowledge — but they cannot easily ask questions of it.

The arrival of large language models changed what was possible. Suddenly,
the gap between a business question and a data answer felt bridgeable.
But every proof of concept I saw had the same flaw: it worked for demos
and broke for production. The LLM hallucinated facts. The retrieval missed
precise structured answers. The architecture did not fit the SAP ecosystem
that customers already had invested in.

This book is my answer to that problem.

It builds a real system — not a toy — that combines two retrieval strategies
that together handle what neither handles alone. It runs on platforms that
SAP developers already know: SAP BTP, SAP HANA Cloud, and CAP Node.js.
It uses Google Vertex AI not because it is the only option, but because it
is excellent, well-documented, and free to get started with.

Every line of code in this book has been written and tested. Every
architecture decision has a reason. Where I made a tradeoff, I say so.

My hope is that you finish this book with a working system deployed on
SAP BTP, a clear mental model of how agentic AI actually works, and the
confidence to take these patterns into your own projects.

Let us build something real.

**Sriram Rokkam**
*May 2026*

---

## Who This Book Is For

This book is written for:

- **SAP developers and architects** familiar with SAP BTP, CAP, or ABAP
  who want to build AI-powered applications on the platform they already know
- **AI and ML engineers** working in SAP customer environments who need
  to understand the SAP data layer and how to integrate with it
- **Technical leads and solution architects** evaluating agentic AI patterns
  for SAP projects and looking for a production-ready reference architecture
- **Full-stack developers** who have experimented with LLMs and chatbots
  and are ready to go beyond simple Q&A into multi-step agentic systems
- **BTP developers** who want hands-on experience with SAP HANA Cloud's
  vector engine and SPARQL Knowledge Graph capabilities

If you work with SAP systems and want to build AI agents that reason over
your enterprise data — this book is for you.

---

## Who This Book Is NOT For

This book is not the right fit if you are:

- **Looking for a general machine learning or deep learning introduction.**
  We do not cover neural networks, training models, or ML theory.
  This book is about applying LLMs to SAP problems, not building LLMs.

- **An ABAP developer with no Python experience.**
  The agent layer is written in Python. You do not need to be an expert,
  but you should be comfortable reading and writing basic Python functions,
  classes, and pip packages before starting Chapter 2.

- **Looking for a no-code or low-code AI solution.**
  We write real code throughout. Every component is built from first
  principles so you understand exactly what it does and why.

- **Expecting SAP AI Core as the primary AI backend.**
  We use Google Vertex AI (Gemini + text-embedding-004) because it is
  available on the free trial. SAP AI Core is covered in Appendix E
  for readers who have an enterprise subscription.

- **New to cloud development entirely.**
  You should be comfortable with the concept of cloud services, REST APIs,
  and deploying applications. Chapter 2 walks through all the setup steps,
  but it assumes you have used a terminal before.

---

## Prerequisites

### Technical Knowledge

The following knowledge is assumed. You do not need to be an expert —
a working familiarity is enough.

| Topic | Level Required | Where to Learn if Needed |
|-------|---------------|--------------------------|
| Python | Basic — functions, classes, pip, venv | python.org/about/gettingstarted |
| JavaScript / Node.js | Basic — enough to read CAP handlers | nodejs.dev/learn |
| SAP BTP concepts | Familiar — subaccounts, CF, services | learning.sap.com |
| REST APIs | Basic — HTTP methods, JSON | Any REST API tutorial |
| SQL | Basic — SELECT, INSERT | W3Schools SQL |

### NOT Required

You do not need prior knowledge of:
- Machine learning theory or mathematics
- LangChain or LangGraph (we introduce it from scratch in Chapter 6)
- RDF, SPARQL, or Knowledge Graphs (introduced from scratch in Chapter 4)
- SAP AI Core (covered optionally in Appendix E)
- ABAP development
- Docker or Kubernetes

### Tools and Accounts (All Free)

All tools and accounts are free. Chapter 2 walks through every setup step.

| Tool / Account | Purpose | Cost |
|---------------|---------|------|
| SAP BTP Trial | Runtime, HANA Cloud, CAP deployment | Free |
| GCP Account | Vertex AI API (Gemini + embeddings) | Free ($300 credit) |
| Python 3.11+ | Agent development | Free |
| Node.js 20+ | CAP frontend development | Free |
| CF CLI | Deploy to BTP Cloud Foundry | Free |
| CDS CLI (`@sap/cds-dk`) | CAP development | Free |
| VS Code | Code editor | Free |

---

## Companion Code Repository

All source code for this book lives in a single GitHub repository:

```
https://github.com/sriramrokkam/book-agentic-hybrid-rag-on-btp
```

### Repository Structure

```
book-agentic-hybrid-rag-on-btp/
├── agents/                # Python FastAPI + LangGraph agent layer
│   ├── agents/            #   LangGraph chains and orchestrator
│   ├── srv/               #   HANA, vector, KG, and doc services
│   ├── main.py            #   FastAPI entrypoint — all HTTP endpoints
│   ├── requirements.txt
│   └── .env.example       #   Required environment variables template
├── cap-srv/               # CAP Node.js OData V4 service
│   ├── db/schema.cds      #   Data model
│   ├── srv/service.cds    #   Service definition and actions
│   ├── srv/service.js     #   Action handlers (proxies to agent layer)
│   └── .env.example
├── MSDS_Ontology.ttl      # OWL ontology constraining Knowledge Graph
├── docs/                  # Book chapters and screenshots (this folder)
│   ├── CODE_MAP.md        #   Chapter → source file cross-reference
│   └── chapters/          #   All chapter markdown files
└── README.md              # Complete local setup guide
```

### Quick Start

```bash
# 1. Clone
git clone https://github.com/sriramrokkam/book-agentic-hybrid-rag-on-btp.git
cd book-agentic-hybrid-rag-on-btp

# 2. Set up Python environment
python3 -m venv agents/.venv
source agents/.venv/bin/activate
pip install -r agents/requirements.txt

# 3. Configure credentials
cp agents/.env.example agents/.env
# Edit agents/.env — see README.md for where to find each value

# 4. Run the agent layer
uvicorn agents.main:app --reload --host 0.0.0.0 --port 8000

# 5. Run the CAP layer (separate terminal)
cd cap-srv && npm install && cds serve
```

See `README.md` in the repository root for the complete step-by-step
setup guide, including all environment variables, endpoints, and
deployment instructions for SAP BTP Cloud Foundry.

### Chapter-to-Code Cross-Reference

`docs/CODE_MAP.md` maps every chapter to the exact source files and
functions it covers. Use it to jump directly to the code for any
chapter without searching the repository.

---

## How to Use This Book

### Reading Cover to Cover (Recommended)

Each chapter builds directly on the previous one. The system grows
chapter by chapter — by Chapter 9 you have a fully deployed, working
Hybrid RAG Agent on SAP BTP. Reading linearly gives you the full
progression from concept to production.

### As a Reference

If you already have some of the pieces (a HANA Cloud instance, some
LangGraph experience), jump to the chapter you need. Each chapter opens
with a summary of what it assumes you already have from previous chapters.

### Chapter Structure

Every chapter in this book follows the same pattern:

1. **Opening question** — the single question this chapter answers
2. **Concept** — the idea explained in plain language before any code
3. **Code** — we build the component step by step
4. **Explanation** — what each part does and why it is designed that way
5. **Test** — how to verify it works before moving on
6. **Summary** — what we built and what comes next
7. **Checkpoint** — a checklist before starting the next chapter

### The Code

All code is in the companion GitHub repository:

```
https://github.com/sriramrokkam/book-agentic-hybrid-rag-on-btp
```

Each chapter has a corresponding folder in the repo. If you get stuck,
the repo has the complete working code for reference.

---

## Conventions Used in This Book

### Code Blocks

```python
# Python code appears in blocks like this
def example():
    return "this is a code example"
```

```javascript
// JavaScript/Node.js code looks like this
const example = () => "this is a code example";
```

```bash
# Terminal commands look like this
cf push my-app
```

```sql
-- SQL queries look like this
SELECT * FROM MY_TABLE;
```

### Callout Boxes

> **Note:** Additional context or clarification that is helpful but
> not critical to follow along.

> **Important:** Something you must do or understand before continuing.
> Skipping this will cause problems later.

> **Warning:** A common mistake or pitfall. Pay attention here.

> **Tip:** A shortcut, best practice, or time-saving suggestion.

### File Paths

File paths are shown relative to the project root:
- `agents/srv/hdb_srv.py` — the HANA connection service in the agents module
- `cap-srv/db/schema.cds` — the CDS data model

### Screenshots

Screenshots show the state of the UI at the time of writing. SAP BTP
and GCP update their interfaces regularly. If a screen looks slightly
different, the underlying action is the same — use the search or
navigation to find the equivalent option.

`[SCREENSHOT: description]` markers in this draft will be replaced
with actual screenshots in the final published version.

---

---

## About the Author

**Sriram Rokkam** is a Global Business AI Architect at SAP with over 20 years of experience in SAP Supply Chain Management and enterprise platform engineering. He works at the intersection of SAP BTP, Google Cloud Platform, and applied AI — spanning predictive analytics, generative AI, and agentic systems.

A hands-on engineer and practitioner, Sriram has designed and built AI-powered solutions across supply chain, procurement, and quality management domains. He is passionate about making agentic AI practical and production-ready for SAP customers — not as a research exercise, but as running software that solves real business problems.

He writes and builds at the intersection of LangGraph, SAP HANA Cloud, and Google Vertex AI. His work on hybrid RAG architectures for SAP environments forms the foundation of this book.

- **GitHub:** github.com/sriramrokkam
- **LinkedIn:** linkedin.com/in/sriramrokkam

---

*End of Front Matter — Chapter 1 begins on the next page.*
