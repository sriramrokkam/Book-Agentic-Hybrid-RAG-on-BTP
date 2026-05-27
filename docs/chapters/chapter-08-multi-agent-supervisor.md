# Chapter 8: The Multi-Agent Supervisor Pattern

In Chapter 7 we built a hybrid RAG agent that runs two retrieval strategies in parallel and merges their results. For the majority of questions — "what are the hazard codes?", "what are the storage instructions?" — that agent is the right tool. It is fast, deterministic, and requires no coordination overhead.

But consider a different class of question: "I am setting up a new chemical storage facility that will handle acetone. What hazard classifications do I need to post, what are the legal worker exposure limits, and what personal protective equipment should I provide?" That question requires three distinct types of expertise: GHS classification knowledge, regulatory compliance knowledge, and safety procedure knowledge. A single agent with a single retrieval pass will mix these domains, risk missing one, and produce an answer that is harder to reason about.

This is the complexity ceiling of a single-agent system. When a question spans multiple domains and each domain requires focused, specialised reasoning, a team of specialist agents produces better answers than a generalist agent working alone.

This chapter introduces the **supervisor pattern**: a coordinator agent that receives complex questions, decomposes them, routes sub-questions to specialist agents, and synthesises their results into a final answer. The pattern is demonstrated with MSDS-specific specialists, but the architecture is general — the same supervisor, state machine, and merge logic apply to any SAP document type.

---

## 8.1 Why multi-agent for SAP enterprise

A generalist agent has one prompt, one retrieval context, and one LLM call to produce its answer. When questions are simple and focused, this is efficient. When questions are complex and multi-domain, it creates three problems.

**Problem 1: Context dilution.** A single retrieval pass retrieves the top-5 passages by cosine similarity. For a multi-domain question, those 5 passages will be distributed across domains — perhaps 2 about hazards, 2 about storage, 1 about first aid. Each domain gets insufficient context.

**Problem 2: Prompt overloading.** The LLM receives a long prompt with mixed signals. It must simultaneously reason about regulatory thresholds, GHS classifications, and PPE requirements. The answer tends to be shallow across all three rather than deep on any one.

**Problem 3: Uneven retrieval strategy per domain.** Different document sections require different retrieval strategies. A question about GHS hazard codes (structured data) is best answered from the knowledge graph, where codes and descriptions are stored as precise triples. A question about first aid procedures (narrative text) is best answered from the vector store, where the prose of Section 4 lives. A question about regulatory compliance requires both — structured exposure limits from the KG and narrative regulatory context from the vector store. A generalist agent applies one strategy to all three. A specialist agent applies the right strategy to its domain.

The supervisor pattern solves all three by decomposing the question *before* retrieval — routing each sub-question to a specialist that uses the correct retrieval strategy for that knowledge type.

---

## 8.2 The supervisor pattern

The supervisor pattern has four components:

| Component | Role |
|---|---|
| **Supervisor** | Receives the user question, decomposes it into sub-questions, routes each to the right specialist, collects results |
| **Specialist agents** | Each handles one focused domain — retrieves relevant data using the right strategy, generates a domain-specific answer |
| **SummaryAgent** | Receives all specialist answers, synthesises them into a single coherent response |
| **Shared state** | Carries the original question, sub-questions, and all specialist answers through the graph |

![Multi-Agent Supervisor Pattern](docs/screenshots/diagrams/09-supervisor-pattern.png)
*Figure 8.1: The multi-agent supervisor — the supervisor decomposes the question and routes sub-questions to specialist agents running in parallel. The SummaryAgent synthesises all results into the final answer.*

The supervisor does not answer the question. It only routes. This separation of concerns is what makes the pattern scale: you can add a new specialist agent without changing the supervisor prompt, and each specialist can be optimised independently.

---

## 8.3 The three specialist agents for MSDS documents

For MSDS documents, the domain decomposition maps naturally to three specialist agents. Each agent uses a different retrieval strategy because each domain has a different knowledge representation:

### 8.3.1 HazardAgent

**Domain:** GHS classifications, hazard codes, hazard statements, signal words.
**Retrieval strategy:** Knowledge graph — structured facts from `hasHazardCode` and `hazardDescription` predicates in `MSDS_Graph/MAT-XXX`.
**Strength:** Returns exact codes (H225, H319, H336) and their official descriptions directly from structured triples — no ambiguity, no narrative interpretation.

### 8.3.2 SafetyAgent

**Domain:** Precautions, first aid procedures, PPE requirements, storage and handling instructions.
**Retrieval strategy:** Vector search — narrative text from Sections 4, 7, and 8 of the MSDS.
**Strength:** Returns detailed procedural instructions that live in prose and are not easily reduced to structured triples. The vector store retrieves the specific paragraphs that answer the question.

### 8.3.3 ComplianceAgent

**Domain:** Regulatory requirements, exposure limits, permissible concentrations, legal obligations.
**Retrieval strategy:** Both KG and vector — structured exposure limits from `hasExposureLimit` predicates, combined with narrative regulatory context from the vector store.
**Strength:** Handles questions that span structured facts (the OSHA limit is 500 ppm TWA) and regulatory narrative (what that limit means and how to comply with it).

These three agents are MSDS-specific instances of a general pattern. The same supervisor architecture deployed for purchase order documents would have different specialists: a HeaderAgent for invoice metadata, a LineItemAgent for line item details, a PaymentAgent for payment terms and status. The routing logic, the state machine, and the merge mechanism are identical. Only the specialist prompts and the KG predicates they query change.

---

## 8.4 Shared state for the supervisor graph

Create `agents/agents/supervisor_state.py`:

```python
from typing import TypedDict, List, Optional, Dict

class SupervisorState(TypedDict):
    # Input
    question: str
    material_number: str
    history: List[dict]

    # Decomposed sub-questions (set by supervisor)
    sub_questions: Dict[str, str]   # {"hazard": "...", "compliance": "...", "safety": "..."}
    specialists_needed: List[str]   # e.g. ["hazard", "compliance"]

    # Specialist outputs
    hazard_answer: str
    compliance_answer: str
    safety_answer: str

    # Final output
    final_answer: str
    sources: List[str]

    # Control
    error: Optional[str]
```

The `sub_questions` dictionary maps specialist names to the focused questions the supervisor generated for them. `specialists_needed` is the list of specialists the supervisor decided to invoke — not every question needs all three. A question purely about GHS codes routes only to HazardAgent. A question about storage and compliance routes to SafetyAgent and ComplianceAgent.

---

## 8.5 The supervisor node

The supervisor's job is to read the user's question and decide which specialists are needed and what sub-question to give each one. This is a routing decision, and routing decisions should be deterministic — temperature 0.0.

```python
import json
import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

def _get_llm():
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0, max_tokens=512)

SUPERVISOR_PROMPT = """You are a routing agent for a material document intelligence system on SAP BTP.
Your job is to analyse a user's question and route it to the right specialist agents.

Each specialist uses a different retrieval strategy — route to the specialist whose strategy best matches the question type:
- "hazard": answers questions about structured facts — GHS hazard codes, hazard classifications, signal words, hazard statements. Uses the knowledge graph.
- "compliance": answers questions about regulatory requirements — exposure limits, permissible concentrations, OSHA/ACGIH thresholds, legal obligations. Uses both knowledge graph and document search.
- "safety": answers questions about narrative procedures — first aid, PPE requirements, storage instructions, handling precautions, spill response. Uses document search.

For each specialist you select, write a focused sub-question that extracts only the relevant part of the user's question.

Respond in JSON format only:
{{
  "specialists": ["hazard", "compliance", "safety"],
  "sub_questions": {{
    "hazard": "What GHS hazard codes and classifications apply to {material}?",
    "compliance": "What are the worker exposure limits for {material}?",
    "safety": "What PPE and handling precautions are required for {material}?"
  }}
}}

Select only the specialists that are relevant. A simple question may need only one.

Material: {material}
Question: {question}

JSON:"""

def supervisor_node(state: SupervisorState) -> dict:
    question = state["question"]
    material_number = state["material_number"]

    prompt = SUPERVISOR_PROMPT.format(
        material=material_number,
        question=question,
    )
    response = _get_llm().invoke([HumanMessage(content=prompt)])
    content = response.content.strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        content = "\n".join(content.split("\n")[1:-1])

    try:
        routing = json.loads(content)
        return {
            "specialists_needed": routing.get("specialists", ["hazard", "compliance", "safety"]),
            "sub_questions": routing.get("sub_questions", {}),
        }
    except json.JSONDecodeError:
        logger.warning("Supervisor JSON parse failed, routing to all specialists")
        return {
            "specialists_needed": ["hazard", "compliance", "safety"],
            "sub_questions": {
                "hazard": question,
                "compliance": question,
                "safety": question,
            },
        }
```

The fallback on JSON parse failure routes to all specialists, which is safe: slightly slower, never wrong. It is better to over-route than to drop a domain.

---

## 8.6 The specialist agents

Each specialist is a focused invocation of the hybrid RAG chains from Chapter 7, configured with the correct retrieval strategy for its domain.

```python
import logging
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from agents.supervisor_state import SupervisorState
from agents.kg_chain import run_kg_chain
from agents.vector_chain import run_vector_chain
from agents.state import HybridRAGState

logger = logging.getLogger(__name__)

def _get_llm():
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1, max_tokens=1024)

def _make_chain_state(sub_question: str, state: SupervisorState) -> HybridRAGState:
    """Build a HybridRAGState for a specialist's sub-question."""
    return {
        "question": sub_question,
        "material_number": state["material_number"],
        "history": [],   # specialists do not use conversation history
        "vector_answer": "", "vector_chunks": [],
        "kg_answer": "", "kg_sparql": "", "kg_facts": [],
        "final_answer": "", "sources": [], "error": None,
    }

def hazard_agent(state: SupervisorState) -> dict:
    """KG-focused: GHS codes, classifications, hazard statements.
    Structured hazard data lives in the knowledge graph as precise triples."""
    sub_q = state["sub_questions"].get("hazard", state["question"])
    chain_state = _make_chain_state(sub_q, state)
    result = run_kg_chain(chain_state)
    answer = result.get("kg_answer", "")
    if not answer:
        # Fall back to vector if KG found nothing
        vec_result = run_vector_chain(chain_state)
        answer = vec_result.get("vector_answer", "No hazard information found.")
    return {"hazard_answer": answer}

def compliance_agent(state: SupervisorState) -> dict:
    """KG-focused with vector fallback: exposure limits, regulatory thresholds.
    Structured limits come from the KG; regulatory narrative comes from vector search."""
    sub_q = state["sub_questions"].get("compliance", state["question"])
    chain_state = _make_chain_state(sub_q, state)
    result = run_kg_chain(chain_state)
    answer = result.get("kg_answer", "")
    if not answer:
        vec_result = run_vector_chain(chain_state)
        answer = vec_result.get("vector_answer", "No compliance information found.")
    return {"compliance_answer": answer}

def safety_agent(state: SupervisorState) -> dict:
    """Vector-focused: precautions, first aid, PPE, storage procedures.
    Narrative safety procedures live in document prose — vector search retrieves them."""
    sub_q = state["sub_questions"].get("safety", state["question"])
    chain_state = _make_chain_state(sub_q, state)
    result = run_vector_chain(chain_state)
    answer = result.get("vector_answer", "")
    if not answer:
        kg_result = run_kg_chain(chain_state)
        answer = kg_result.get("kg_answer", "No safety information found.")
    return {"safety_answer": answer}
```

Each specialist wraps the existing chains from Chapter 7 — they are not new implementations, just focused invocations with the correct primary retrieval strategy. HazardAgent and ComplianceAgent use the KG chain first (structured facts are exactly what they need) and fall back to the vector chain if the KG returns nothing. SafetyAgent uses the vector chain first (narrative procedures live in prose) and falls back to KG.

---

## 8.7 The summary agent

```python
def summary_agent(state: SupervisorState) -> dict:
    """Synthesise specialist answers into a final coherent response."""
    parts = []
    if state.get("hazard_answer"):
        parts.append(f"**Hazard Classification:**\n{state['hazard_answer']}")
    if state.get("compliance_answer"):
        parts.append(f"**Regulatory Compliance:**\n{state['compliance_answer']}")
    if state.get("safety_answer"):
        parts.append(f"**Safety Procedures:**\n{state['safety_answer']}")

    if not parts:
        return {
            "final_answer": (
                f"No information found for material {state['material_number']}. "
                "Please verify the material number."
            ),
            "sources": [],
        }

    if len(parts) == 1:
        # Single specialist answered — no synthesis needed
        return {
            "final_answer": list(parts)[0].split("\n", 1)[1],
            "sources": ["Single specialist"],
        }

    combined = "\n\n".join(parts)
    prompt = f"""You are an expert assistant for SAP material documents. Multiple specialist agents have
analysed the question below and provided their answers.

{combined}

Original question: {state['question']}

Synthesise the above into a single, well-organised, professional answer.
- Use headings to separate sections
- Do not repeat information that appears in multiple answers
- Be specific with codes, values, and units
- Write for an enterprise user audience

Answer:"""

    response = _get_llm().invoke([HumanMessage(content=prompt)])
    return {
        "final_answer": response.content,
        "sources": [f"{len(parts)} specialist agents"],
    }
```

---

## 8.8 Building the supervisor graph

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from langgraph.graph import StateGraph, END

from agents.supervisor_state import SupervisorState
from agents.supervisor import supervisor_node
from agents.specialist_agents import hazard_agent, compliance_agent, safety_agent, summary_agent

def parallel_specialists_node(state: SupervisorState) -> dict:
    """Run only the needed specialists in parallel."""
    needed = state.get("specialists_needed", ["hazard", "compliance", "safety"])

    agent_map = {
        "hazard": hazard_agent,
        "compliance": compliance_agent,
        "safety": safety_agent,
    }

    results = {}
    agents_to_run = {name: fn for name, fn in agent_map.items() if name in needed}

    with ThreadPoolExecutor(max_workers=len(agents_to_run)) as executor:
        futures = {executor.submit(fn, state): name for name, fn in agents_to_run.items()}
        for future in as_completed(futures, timeout=60):
            name = futures[future]
            try:
                results.update(future.result(timeout=30))
            except Exception as e:
                import logging
                logging.getLogger(__name__).error("Specialist %s failed: %s", name, e)

    return results

def build_supervisor_graph():
    graph = StateGraph(SupervisorState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("specialists", parallel_specialists_node)
    graph.add_node("summary", summary_agent)

    graph.set_entry_point("supervisor")
    graph.add_edge("supervisor", "specialists")
    graph.add_edge("specialists", "summary")
    graph.add_edge("summary", END)

    return graph.compile()

supervisor_app = build_supervisor_graph()
```

The graph is three nodes: supervisor → specialists (parallel) → summary. The `parallel_specialists_node` runs only the specialists that the supervisor selected, using a `ThreadPoolExecutor` sized to the number of active specialists. If the supervisor selects only two specialists for a focused question, only two threads are created — not three. This avoids unnecessary API calls.

---

## 8.9 When to use the supervisor vs the direct agent

The supervisor adds latency — one extra LLM call for routing and one for synthesis. For simple questions, this overhead is not justified.

| Question type | Recommended agent | Why |
|---|---|---|
| Single-domain factual ("what are the hazard codes?") | Direct hybrid RAG (Ch 7) | Faster, no routing overhead |
| Single-domain narrative ("what is the first aid?") | Direct hybrid RAG (Ch 7) | Faster, single retrieval pass is sufficient |
| Multi-domain factual + narrative ("codes AND precautions") | Supervisor | Each domain gets focused retrieval |
| Complex regulatory + safety question | Supervisor | Prevents context dilution |
| Real-time chat interface | Direct hybrid RAG (Ch 7) | Latency matters in chat |
| Batch compliance reports | Supervisor | Quality matters more than speed |

A practical rule: if the question contains "and" connecting two distinct domains, use the supervisor.

---

## 8.10 The /query-advanced endpoint

Add the supervisor endpoint to `agents/main.py`:

```python
from agents.supervisor import supervisor_app
from agents.supervisor_state import SupervisorState

class AdvancedQueryRequest(BaseModel):
    question: str
    material_number: str
    history: List[dict] = []
    use_supervisor: bool = False

    @validator("material_number")
    def validate_material(cls, v):
        if not re.match(r"^[A-Za-z0-9_-]+$", v):
            raise ValueError("material_number contains invalid characters")
        return v

@app.post("/query-advanced", response_model=QueryResponse)
def query_advanced(request: AdvancedQueryRequest):
    if not request.use_supervisor:
        # Fall back to direct hybrid RAG
        return query(QueryRequest(
            question=request.question,
            material_number=request.material_number,
            history=request.history,
        ))

    state: SupervisorState = {
        "question": request.question,
        "material_number": request.material_number,
        "history": request.history,
        "sub_questions": {},
        "specialists_needed": [],
        "hazard_answer": "",
        "compliance_answer": "",
        "safety_answer": "",
        "final_answer": "",
        "sources": [],
        "error": None,
    }

    result = supervisor_app.invoke(state)

    return QueryResponse(
        answer=result.get("final_answer", ""),
        sources=result.get("sources"),
    )
```

The `use_supervisor` flag lets the caller choose which agent to use. The Fiori UI sends `use_supervisor: true` when it detects certain patterns in the question (multiple question marks, keywords like "and", "also", "as well as"). For simple questions it uses the faster direct endpoint.

---

## 8.11 Testing: a question that requires all three specialists

```bash
curl -X POST http://localhost:8000/query-advanced \
  -H "Content-Type: application/json" \
  -d '{
    "question": "I am setting up a new lab that will store acetone. What hazard classifications do I need to post, what are the legal exposure limits for my workers, and what PPE should I provide?",
    "material_number": "ACE001",
    "history": [],
    "use_supervisor": true
  }'
```

Expected supervisor routing (logged to console):

```
INFO: Supervisor routed to: ['hazard', 'compliance', 'safety']
INFO: Sub-questions:
  hazard:     "What GHS hazard codes and classifications apply to ACE001?"
  compliance: "What are the worker exposure limits for ACE001?"
  safety:     "What PPE is required when storing and handling ACE001?"
INFO: hazard specialist completed in 2.1s
INFO: compliance specialist completed in 1.9s
INFO: safety specialist completed in 2.3s
INFO: All specialists completed in 2.3s (parallel)
INFO: Summary agent completed in 1.4s
```

The three specialists run in parallel. The total wall-clock time for specialists is 2.3 seconds (the slowest), not 6.3 seconds (the sum). The summary adds 1.4 seconds, for a total of about 3.7 seconds.

Compare this to the direct hybrid RAG agent with the same question: the single retrieval pass would retrieve 5 passages from across all three domains, giving the answer approximately 2 passages per domain. The supervisor gives each domain 5 full passages, producing a noticeably more detailed and better-organised answer — especially critical when the question spans GHS codes (structured, from KG), regulatory limits (structured, from KG), and PPE procedures (narrative, from vector store).

---

## 8.12 Applying the pattern to other SAP document types

The multi-agent pattern shown here with MSDS specialisations applies directly to other SAP document types. The supervisor, the state machine, and the merge logic are identical — only the specialist prompts and KG predicates change.

**Batch certificates:** A CertificationAgent checks test results against specification limits using the KG (structured test values and limits are natural graph triples). A SupplierAgent resolves supplier identity from the KG using supplier-linked predicates. A ComplianceAgent checks whether results satisfy regulatory boundaries by querying both the KG for the regulation threshold and the vector store for the compliance narrative.

**Purchase orders and invoices:** A HeaderAgent extracts invoice metadata (vendor, date, currency, document number) from the KG, where these are stored as structured triples. A LineItemAgent retrieves individual line item details using vector search against the prose of the invoice. A PaymentAgent queries both the KG for payment term codes and the vector store for any payment instruction narrative.

**Quality inspection reports:** A ResultsAgent queries the KG for structured test outcome triples (pass/fail verdicts, measured values). A SpecificationAgent queries the KG for specification limits linked to the material. A NonConformanceAgent uses vector search to retrieve the narrative description of any quality issues identified in the report.

In every case: questions about structured, enumerable facts (codes, numbers, identifiers, classifications) route to KG-heavy specialists. Questions about narrative, procedural, or descriptive content route to vector-heavy specialists. Questions that span both route to specialists that use both retrieval strategies. The supervisor makes this routing decision dynamically at query time, without any hard-coded rules.

---

## 8.13 Summary

In this chapter we extended the system from a single agent to a coordinated multi-agent system:

- Identified the **complexity ceiling** of single-agent architectures for multi-domain enterprise questions
- Explained **why different document sections require different retrieval strategies** — structured KG for facts, vector search for procedures, both for compliance
- Designed three **specialist agents** (HazardAgent, SafetyAgent, ComplianceAgent) as MSDS-specific instances of a general pattern
- Built a **supervisor node** that uses Gemini 2.5 Flash to decompose questions and route sub-questions dynamically
- Ran specialists **in parallel** using `ThreadPoolExecutor`, keeping wall-clock latency equal to the slowest specialist
- Implemented the **SummaryAgent** to synthesise multi-domain answers into coherent final responses
- Added a `/query-advanced` endpoint with a `use_supervisor` flag for caller-controlled routing
- Defined clear criteria for **when to use the supervisor** vs the direct hybrid RAG agent
- Showed how **the pattern generalises** to other SAP document types — batch certificates, invoices, inspection reports

The supervisor, state machine, and merge logic are reusable infrastructure. Deploying this pattern for a new document type requires writing three specialist prompts and identifying the relevant KG predicates — the orchestration architecture requires no changes.

---

## 8.14 Checkpoint

Before continuing to Chapter 9, verify the following:

```bash
# 1. Supervisor graph compiles
cd agents
python -c "
from agents.supervisor import build_supervisor_graph
app = build_supervisor_graph()
print('Supervisor graph OK, nodes:', list(app.get_graph().nodes.keys()))
"

# 2. Supervisor routes correctly on a simple question
python -c "
from agents.supervisor import supervisor_node
state = {
  'question': 'What are the hazard codes for acetone?',
  'material_number': 'ACE001',
  'history': [],
  'sub_questions': {}, 'specialists_needed': [],
  'hazard_answer': '', 'compliance_answer': '', 'safety_answer': '',
  'final_answer': '', 'sources': [], 'error': None,
}
result = supervisor_node(state)
print('specialists needed:', result['specialists_needed'])
"

# 3. The advanced endpoint responds
curl -s -X POST http://localhost:8000/query-advanced \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "What are the GHS hazard codes for acetone?",
    "material_number": "ACE001",
    "history": [],
    "use_supervisor": false
  }' | python -m json.tool
```

If the supervisor graph compiles cleanly, the routing test assigns only `["hazard"]` or a small subset of specialists to a simple question, and the curl returns a valid JSON response — the multi-agent system is working. Chapter 9 exposes this entire backend through the SAP CAP OData V4 service with the Fiori Elements UI.

---

*End of Chapter 8*
