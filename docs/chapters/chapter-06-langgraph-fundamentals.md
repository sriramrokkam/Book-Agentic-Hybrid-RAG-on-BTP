# Chapter 6: LangGraph Fundamentals

In Chapter 5 we built a document ingestion pipeline that processes PDFs into both a vector store and a Knowledge Graph simultaneously. We now have data — rich, structured, searchable data — in SAP HANA Cloud. The next question is: how do we build an agent that reasons over it in a way that is auditable, inspectable, and safe to deploy on BTP?

A plain LangChain chain would work for a single retrieval followed by a single LLM call. But the system we need is more complex than that. It needs to run two retrieval strategies in parallel, decide how to merge their results, handle retries when SPARQL returns empty results, maintain conversation history across turns, and expose all of this over a single HTTP endpoint. A linear chain cannot express those decisions. We need something that can branch, loop, and conditionally route based on what it finds.

That something is LangGraph.

This chapter introduces LangGraph from first principles. We build a simple question-answering agent step by step — one node at a time — so that when Chapter 7 extends it into the full parallel hybrid RAG system, every piece is familiar. By the end of this chapter you will have a running LangGraph agent connected to Vertex AI, and you will understand exactly how state flows through it.

---

## 6.1 Why LangGraph is SAP's recommended orchestration approach for BTP agents

Enterprise AI governance requires more than a correct answer. It requires an auditable trail: which system provided which data, which decision was made at which step, and why. When an auditor asks "how did the system determine that the exposure limit was 500 ppm?", you need to be able to show the SPARQL query, the HANA result, and the LLM call that synthesised it into natural language. A black-box chain gives you none of that. A LangGraph StateGraph gives you all of it.

LangGraph models your agent as a directed graph rather than a list. Every node in the graph is a named Python function. Every state transition is an explicit edge. Every intermediate result is captured in the graph state. LangGraph traces can be exported to LangSmith, where each run shows a complete tree: which nodes executed, in what order, what the state contained at each step, and the exact prompts sent to Gemini. This execution trace is the enterprise AI governance artefact.

The conceptual mapping to SAP BTP workflow constructs is direct:

| LangGraph concept | BTP workflow equivalent |
|---|---|
| `AgentState` (TypedDict) | BTP Workflow context object |
| Node (Python function) | Workflow service task step |
| Edge | Sequence flow between steps |
| Conditional edge | Exclusive gateway (XOR decision) |
| `StateGraph.compile()` | Deployed workflow definition |
| `app.invoke(state)` | Workflow instance execution |

SAP's own internal AI agent frameworks use LangGraph for exactly this reason: the execution model is transparent, the state is inspectable at any point, and the graph definition is a first-class artefact that can be reviewed, versioned, and audited like any other software component.

---

## 6.2 Why LangChain chains are not enough

LangChain introduced the concept of a chain: a sequence of components where the output of one feeds the input of the next. For many tasks — retrieve a passage, summarise it, return the result — a chain is exactly right. It is simple, readable, and easy to test.

The problem arises when your logic is not a sequence. Consider what our hybrid RAG system needs to do:

| Requirement | Can a chain do it? |
|---|---|
| Run two retrieval strategies in parallel | No — chains are sequential |
| Retry SPARQL generation if results are empty | No — chains have no loops |
| Route to different merge strategies based on what was found | No — chains have no conditional branches |
| Pass conversation history into every step | Awkward — requires passing state manually |
| Produce an auditable execution trace | No — chain execution is opaque |

LangGraph solves every one of these by modelling your agent as a directed graph rather than a list. Nodes are Python functions. Edges are connections between them. Conditional edges let the graph branch based on the current state. The graph can loop. It can run nodes in parallel. It can capture and stream intermediate results.

> **Note:** LangGraph is built on top of LangChain. You still use LangChain components — `ChatVertexAI`, `tool` decorators, message types — but LangGraph provides the execution engine that orchestrates them.

---

## 6.3 Core concepts

Before writing any code, here are the four concepts you need to hold in your head.

### 6.3.1 State

State is the memory of your agent for a single run. It is a Python `TypedDict` — a dictionary where every key has a declared type. Every node in the graph reads from state and writes back to state. State is the only way nodes communicate with each other.

In BTP workflow terms, state is the context object that a workflow instance carries from step to step. When you inspect a running workflow in BTP Process Automation, you see this context. In LangGraph, when you inspect a run in LangSmith, you see the state at each node boundary. The concept is identical.

```python
from typing import TypedDict, List

class AgentState(TypedDict):
    question: str
    answer: str
    messages: List[dict]
```

When you invoke the graph, you pass an initial state. When the graph finishes, you receive the final state. Everything that happened in between is recorded there.

### 6.3.2 Nodes

A node is a Python function that receives the current state and returns a partial update to it. LangGraph merges the update into the state before passing it to the next node. In BTP workflow terms, a node is a service task — it does one focused piece of work and writes its result to the workflow context.

```python
def my_node(state: AgentState) -> dict:
    question = state["question"]
    answer = call_llm(question)
    # return only the keys you want to update
    return {"answer": answer}
```

The function does not need to return the entire state — only the keys it wants to change. LangGraph merges the returned dict into the existing state automatically.

### 6.3.3 Edges

An edge connects two nodes. When node A finishes, LangGraph follows the edge to node B and runs it next. This is a sequence flow in BTP workflow terms — deterministic, always-true routing.

```python
graph.add_edge("node_a", "node_b")
```

### 6.3.4 Conditional edges

A conditional edge calls a routing function after a node completes. The routing function inspects the state and returns a string that names the next node to run. In BTP workflow terms, this is an exclusive gateway: examine the context, choose one outgoing sequence flow.

```python
def route(state: AgentState) -> str:
    if state["answer"] == "":
        return "retry"
    return "done"

graph.add_conditional_edges("node_a", route, {
    "retry": "retry_node",
    "done": END
})
```

This is how loops and branches are expressed in LangGraph.

---

## 6.4 Installation and project layout

Install LangGraph and the Google GenAI integration. Note the correct import: `langchain_google_genai`, not `langchain_google_vertexai` — the VertexAI variant is deprecated for the Gemini model family.

```bash
pip install langgraph langchain-google-genai langchain-core
```

Add these to `agents/requirements.txt`:

```
langgraph>=0.2.0
langchain-google-genai>=2.0.0
langchain-core>=0.3.0
```

We will build the simple agent in a new file:

```
agents/
  agents/
    simple_qa_agent.py    ← this chapter
    orchestrator.py       ← Chapter 7
    kg_chain.py           ← Chapter 7
    vector_chain.py       ← Chapter 7
```

---

## 6.5 Building the state and nodes

Open `agents/agents/simple_qa_agent.py`. We start with the state definition and two nodes.

```python
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage
# ── State ─────────────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    question: str
    context: str
    answer: str
    messages: List[dict]
    retry_count: int
# ── LLM ───────────────────────────────────────────────────────────────────────
def _get_llm():
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1, max_tokens=1024)
# ── Nodes ──────────────────────────────────────────────────────────────────────
def retrieve_node(state: AgentState) -> dict:
    """Stub retriever — replaced by vector + KG chains in Chapter 7."""
    question = state["question"]
    context = f"[Retrieved context for: {question}]"
    return {"context": context}

def answer_node(state: AgentState) -> dict:
    """Generate an answer using the retrieved context."""
    question = state["question"]
    context  = state["context"]
    history  = state.get("messages", [])

    messages = []
    for msg in history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))

    prompt = f"""You are an expert assistant for SAP material documents — you help users find information across PDF documents linked to SAP Material Numbers.

Context from the knowledge base:
{context}

Answer the following question based on the context above.
If the context does not contain enough information, say so clearly.

Question: {question}"""

    messages.append(HumanMessage(content=prompt))
    response = _get_llm().invoke(messages)
    return {"answer": response.content}
```

Two things to notice. First, `retrieve_node` is a deliberate stub — it returns a placeholder string. We build the real retrieval in Chapter 7; this stub lets us test the graph structure now without needing a live HANA connection. Second, `answer_node` builds the conversation history from the `messages` list in state. This is how multi-turn conversations work: the caller passes previous turns in the initial state, and the node includes them in the prompt.

LLM instantiation uses a lazy getter `_get_llm()` rather than a module-level variable. This prevents the LLM client from being initialised at import time, which would fail in environments where credentials are not yet available — a common issue in BTP CF where environment variables are injected after application startup.

---

## 6.6 Wiring the graph

Add the graph construction below the node functions:

```python
def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("retrieve", retrieve_node)
    graph.add_node("answer",   answer_node)

    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer",   END)

    return graph.compile()

app = build_graph()
```

The graph is linear: retrieve → answer → END. To invoke it:

```python
if __name__ == "__main__":
    result = app.invoke({
        "question":    "What test method was used for the tensile strength test?",
        "context":     "",
        "answer":      "",
        "messages":    [],
        "retry_count": 0,
    })
    print(result["answer"])
```

Run it:

```bash
cd agents
python -m agents.simple_qa_agent
```

Expected output (with stub retriever):

```
Based on the provided context, I don't have specific test method details for the tensile strength test.
The context contains a placeholder rather than actual document data. Once the
knowledge base is populated with real documents linked to the material number,
I will be able to retrieve and report the specific information.
```

The agent runs, reaches Gemini 2.5 Flash, and gives an honest answer about the stub context. That is the graph working correctly.

---

## 6.7 Adding a conditional retry edge

Real retrieval can fail — SPARQL returns empty results, an embedding call times out. We need to be able to retry. Add a check node and a routing function:

```python
def check_answer_node(state: AgentState) -> dict:
    """Check if the answer is acceptable. Increment retry counter if not."""
    answer      = state.get("answer",      "")
    retry_count = state.get("retry_count", 0)

    low_quality_phrases = [
        "don't have", "no information", "cannot find",
        "not available", "placeholder"
    ]
    needs_retry = any(p in answer.lower() for p in low_quality_phrases)
    return {"retry_count": retry_count + (1 if needs_retry else 0)}

def route_after_check(state: AgentState) -> str:
    """Decide whether to retry or finish."""
    answer      = state.get("answer",      "")
    retry_count = state.get("retry_count", 0)

    low_quality_phrases = [
        "don't have", "no information", "cannot find",
        "not available", "placeholder"
    ]
    needs_retry = any(p in answer.lower() for p in low_quality_phrases)

    if needs_retry and retry_count < 2:
        return "retry"
    return "done"
```

This is a conditional edge acting as a decision gateway. The routing function reads two state fields — `answer` and `retry_count` — and returns one of two named outcomes. LangGraph maps those outcomes to the next node using the dictionary passed to `add_conditional_edges`. This is identical to how an exclusive gateway in BTP Process Automation evaluates a context condition and routes to one of several outgoing flows.

Update `build_graph` to include the check node and conditional edge:

```python
def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("retrieve", retrieve_node)
    graph.add_node("answer",   answer_node)
    graph.add_node("check",    check_answer_node)

    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer",   "check")

    graph.add_conditional_edges(
        "check",
        route_after_check,
        {
            "retry": "retrieve",   # loop back
            "done":  END
        }
    )

    return graph.compile()
```

The graph now has a loop: retrieve → answer → check → (retry: back to retrieve) or (done: END). The `retry_count` guard prevents infinite loops — after two retries we accept whatever answer we have.

> **Note:** In Chapter 7 the retry logic is more specific: we only retry when SPARQL returns zero results, and the retry uses a simpler SPARQL query, not a full re-run of both chains. The pattern here is the same; the condition is different.

---

## 6.8 The StateGraph visualised

The graph we built in this chapter has three nodes and one conditional loop:

![LangGraph StateGraph Flow](docs/screenshots/diagrams/07-langgraph-state-graph.png)
*Figure 6.1: The simple Q&A agent's StateGraph — retrieve feeds answer, which feeds the check node. The check node either loops back to retrieve (on low-quality answers, up to 2 retries) or terminates at END. The dashed box on the right shows the AgentState structure that flows through every node.*

---

## 6.9 The complete simple_qa_agent.py

```python
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage

class AgentState(TypedDict):
    question:    str
    context:     str
    answer:      str
    messages:    List[dict]
    retry_count: int

def _get_llm():
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.1, max_tokens=1024)

def retrieve_node(state: AgentState) -> dict:
    question = state["question"]
    return {"context": f"[Retrieved context for: {question}]"}

def answer_node(state: AgentState) -> dict:
    messages = []
    for msg in state.get("messages", []):
        cls = HumanMessage if msg["role"] == "user" else AIMessage
        messages.append(cls(content=msg["content"]))

    prompt = f"""You are an expert assistant for SAP material documents — you help users find information across PDF documents linked to SAP Material Numbers.

Context:
{state['context']}

Question: {state['question']}
Answer:"""
    messages.append(HumanMessage(content=prompt))
    return {"answer": _get_llm().invoke(messages).content}

def check_answer_node(state: AgentState) -> dict:
    low = ["don't have", "no information", "cannot find", "not available", "placeholder"]
    needs_retry = any(p in state.get("answer","").lower() for p in low)
    return {"retry_count": state.get("retry_count", 0) + (1 if needs_retry else 0)}

def route_after_check(state: AgentState) -> str:
    low = ["don't have", "no information", "cannot find", "not available", "placeholder"]
    needs_retry = any(p in state.get("answer","").lower() for p in low)
    return "retry" if (needs_retry and state.get("retry_count",0) < 2) else "done"

def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("answer",   answer_node)
    graph.add_node("check",    check_answer_node)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer",   "check")
    graph.add_conditional_edges("check", route_after_check,
                                {"retry": "retrieve", "done": END})
    return graph.compile()

app = build_graph()

if __name__ == "__main__":
    result = app.invoke({
        "question":    "What test method was used for the tensile strength test?",
        "context":     "",
        "answer":      "",
        "messages":    [],
        "retry_count": 0,
    })
    print(result["answer"])
```

---

## 6.10 Tool use in LangGraph

LangGraph supports tools — Python functions that the LLM can choose to call based on the conversation. In a tool-enabled graph, the LLM inspects its available tools, decides which to call, and the selected tool's output is added back into the state for the next node. For the hybrid RAG agent in this book, we deliberately do not use this mechanism — we use direct parallel dispatch of both chains on every query regardless of what the LLM might prefer. The reason is covered in the note below, but understanding tool-enabled graphs is useful if you build agent extensions on top of this platform later.

Define a tool with the `@tool` decorator:

```python
from langchain_core.tools import tool

@tool
def get_test_results(material_number: str) -> str:
    """Retrieve test results for a material from the Knowledge Graph."""
    # In a real implementation this queries HANA SPARQL
    return "ISO 6892-1, yield strength 450 MPa, elongation 22%"
```

Bind tools to the LLM and use `ToolNode` for execution:

```python
from langgraph.prebuilt import ToolNode

tools = [get_test_results]
llm_with_tools = _get_llm().bind_tools(tools)
tool_node = ToolNode(tools)

graph.add_node("tools", tool_node)
graph.add_conditional_edges(
    "answer",
    lambda state: "tools" if state["messages"][-1].tool_calls else END,
    {"tools": "tools", END: END}
)
graph.add_edge("tools", "answer")
```

This creates a tool-calling loop: the LLM inspects the state, decides whether a tool call is needed, and if so, the `ToolNode` executes the selected function and writes the result back to state.

> **Note:** Chapter 7 intentionally avoids this ReAct pattern for the main retrieval. We run both vector and KG chains on every query, regardless of what the LLM might choose. This gives deterministic latency and prevents the LLM from skipping a retrieval path it thinks is unnecessary — a critical property for enterprise systems where consistent, complete answers matter more than adaptive efficiency.

---

## 6.11 Streaming responses

LangGraph can stream state updates as they happen. This is valuable when queries take several seconds — the user sees progress rather than a blank screen.

```python
for event in app.stream({
    "question":    "What are the storage requirements for the material in this batch certificate?",
    "context":     "",
    "answer":      "",
    "messages":    [],
    "retry_count": 0,
}):
    for node_name, state_update in event.items():
        print(f"[{node_name}] completed")
        if "answer" in state_update:
            print(f"  answer: {state_update['answer'][:80]}...")
```

Expected output:

```
[retrieve] completed
[answer] completed
  answer: Store in dry conditions below 25°C away from moisture...
[check] completed
```

> **Tip:** In the FastAPI service, pipe the stream to a Server-Sent Events (SSE) response using `StreamingResponse`. The Fiori UI can consume the stream and update the chat interface progressively as each node completes. We implement this in Chapter 9.

---

## 6.12 Debugging with LangSmith

LangSmith is LangChain's observability platform. It records every LangGraph run — inputs, outputs, intermediate states, LLM calls, latency, and token counts. For an enterprise AI governance use case, LangSmith is the audit log.

Set three environment variables:

```bash
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
export LANGCHAIN_API_KEY=your-api-key-here
```

In your BTP CF `manifest.yml`, add the same variables:

```yaml
applications:
  - name: hybrid-rag-agent
    env:
      LANGCHAIN_TRACING_V2: "true"
      LANGCHAIN_ENDPOINT: "https://api.smith.langchain.com"
      LANGCHAIN_API_KEY: ((langchain-api-key))
```

Use a BTP User-Provided Service to supply the API key without storing it in the manifest. In the LangSmith dashboard you will see a tree view of each run: which nodes executed, in what order, how long each took, and the exact prompt sent to Gemini. When Chapter 7's parallel chains run, you will see two branches executing simultaneously — a visual confirmation that the `ThreadPoolExecutor` parallelism is working.

> **Tip:** Tag your runs in `app.invoke(config={"metadata": {"material_number": material_number}})` and filter by `metadata.material_number` in LangSmith to see all queries against a specific SAP Material Number. This is the query-level audit trail that enterprise governance teams require.

---

## 6.13 Why stateless works on BTP Cloud Foundry

A common concern when deploying LangGraph to Cloud Foundry is: what happens to agent state when you scale to multiple instances?

The answer is: nothing, because there is no server-side state to worry about.

LangGraph state is in-memory for a single request. When `app.invoke()` returns, the state is gone. There is no database, no session file, no sticky session required.

| Concern | Reality |
|---|---|
| CF runs 10 instances | Each request lands on any instance — fine |
| CF restarts an instance | No state is lost — state only exists during a request |
| Two users query simultaneously | Each gets their own independent in-memory state |
| Conversation history | Passed in `messages` field of every request body by the caller |

The conversation history pattern — where the client sends previous turns in every request — is the key. The CAP Fiori frontend stores the last N messages and sends them with each new question.

```python
# Frontend sends history on every request
# POST /query
{
  "question": "And what about the certified testing laboratory?",
  "material_number": "BATCH-QC-MAT-001",
  "history": [
    {"role": "user",      "content": "What test method was used for the tensile strength test?"},
    {"role": "assistant", "content": "The tensile test used ISO 6892-1 methodology with 450 MPa yield strength."}
  ]
}
```

The agent picks up the conversation exactly where it left off — without any server-side memory. This design is safe to scale horizontally on BTP CF without load balancer sticky sessions or shared caches.

---

## 6.14 Summary

In this chapter we built a LangGraph agent from scratch and grounded every concept in SAP BTP enterprise terms:

- Defined **state** as a `TypedDict` that flows through every node — the workflow context object
- Wrote **nodes** as plain Python functions that read state and return partial updates — the workflow service tasks
- Connected nodes with **edges** and **conditional edges** to express branching and looping — sequence flows and exclusive gateways
- Added a **retry loop** that re-runs retrieval when the answer quality is low
- Demonstrated **tool use** with the `@tool` decorator and `ToolNode`
- Enabled **streaming** to show node-level progress events
- Configured **LangSmith** for end-to-end observability and audit trail
- Explained why **stateless design** makes LangGraph safe to scale horizontally on BTP CF

The agent built here uses a stub retriever. In Chapter 7, we replace that stub with the two HANA retrieval chains — vector cosine search and SPARQL — and run them in parallel.

---

## 6.15 Checkpoint

Before continuing to Chapter 7, verify the following:

```bash
# 1. LangGraph is installed
python -c "import langgraph; print(langgraph.__version__)"

# 2. The simple agent runs without errors
cd agents && python -m agents.simple_qa_agent

# 3. Gemini credentials are set
echo $GOOGLE_API_KEY   # or $GOOGLE_APPLICATION_CREDENTIALS for service account

# 4. LangSmith (optional but recommended for governance)
echo $LANGCHAIN_TRACING_V2             # should print "true"
```

If all four commands succeed, you have a working LangGraph agent connected to Gemini 2.5 Flash. Chapter 7 takes this foundation and builds the full parallel hybrid RAG system on top of it — replacing the stub retriever with live HANA vector search and SPARQL execution running in parallel.

---

*End of Chapter 6*
