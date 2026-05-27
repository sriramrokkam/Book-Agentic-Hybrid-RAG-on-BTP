# Chapter 6: LangGraph Fundamentals

In Chapter 5 we built a document ingestion pipeline that processes PDFs into both a vector store and a knowledge graph simultaneously. We now have data — rich, structured, searchable data — in SAP HANA Cloud. The next question is: how do we build an agent that reasons over it?

A plain LangChain chain would work for a single retrieval followed by a single LLM call. But the system we need is more complex than that. It needs to run two retrieval strategies in parallel, decide how to merge their results, handle retries when SPARQL returns empty results, maintain conversation history across turns, and expose all of this over a single HTTP endpoint. A linear chain cannot express those decisions. We need something that can branch, loop, and conditionally route based on what it finds.

That something is LangGraph.

This chapter introduces LangGraph from first principles. We build a simple question-answering agent step by step — one node at a time — so that when Chapter 7 extends it into the full parallel hybrid RAG system, every piece is familiar. By the end of this chapter you will have a running LangGraph agent connected to Vertex AI, and you will understand exactly how state flows through it.

---

## 6.1 Why LangChain chains are not enough

LangChain introduced the concept of a chain: a sequence of components where the output of one feeds the input of the next. For many tasks — retrieve a passage, summarise it, return the result — a chain is exactly right. It is simple, readable, and easy to test.

The problem arises when your logic is not a sequence. Consider what our hybrid RAG system needs to do:

| Requirement | Can a chain do it? |
|---|---|
| Run two retrieval strategies in parallel | No — chains are sequential |
| Retry SPARQL generation if results are empty | No — chains have no loops |
| Route to different merge strategies based on what was found | No — chains have no conditional branches |
| Pass conversation history into every step | Awkward — requires passing state manually |
| Stream partial results to the UI as they arrive | Limited |

LangGraph solves every one of these by modelling your agent as a directed graph rather than a list. Nodes are Python functions. Edges are connections between them. Conditional edges let the graph branch based on the current state. The graph can loop. It can run nodes in parallel. It can stop and stream intermediate results.

> **Note:** LangGraph is built on top of LangChain. You still use LangChain components — `ChatVertexAI`, `tool` decorators, message types — but LangGraph provides the execution engine that orchestrates them.

---

## 6.2 Core concepts

Before writing any code, here are the four concepts you need to hold in your head.

### 6.2.1 State

State is the memory of your agent for a single run. It is a Python `TypedDict` — a dictionary where every key has a declared type. Every node in the graph reads from state and writes back to state. State is the only way nodes communicate with each other.

```python
from typing import TypedDict, List

class AgentState(TypedDict):
    question: str
    answer: str
    messages: List[dict]
```

When you invoke the graph, you pass an initial state. When the graph finishes, you receive the final state. Everything that happened in between is recorded there.

### 6.2.2 Nodes

A node is a Python function that receives the current state and returns a partial update to it. LangGraph merges the update into the state before passing it to the next node.

```python
def my_node(state: AgentState) -> dict:
    question = state["question"]
    answer = call_llm(question)
    # return only the keys you want to update
    return {"answer": answer}
```

The function does not need to return the entire state — only the keys it wants to change. LangGraph merges the returned dict into the existing state automatically.

### 6.2.3 Edges

An edge connects two nodes. When node A finishes, LangGraph follows the edge to node B and runs it next.

```python
graph.add_edge("node_a", "node_b")
```

### 6.2.4 Conditional edges

A conditional edge calls a routing function after a node completes. The routing function inspects the state and returns a string that names the next node to run.

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

## 6.3 Installation and project layout

Install LangGraph and the Vertex AI integration:

```bash
pip install langgraph langchain-google-vertexai langchain-core
```

Add these to `agents/requirements.txt`:

```
langgraph>=0.2.0
langchain-google-vertexai>=2.0.0
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

## 6.4 Building the state and nodes

Open `agents/agents/simple_qa_agent.py`. We start with the state definition and two nodes.

```python
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage, AIMessage
# ── State ─────────────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    question: str
    context: str
    answer: str
    messages: List[dict]
    retry_count: int
# ── LLM ───────────────────────────────────────────────────────────────────────
llm = ChatVertexAI(model_name="gemini-1.5-pro", temperature=0.1, max_tokens=1024)
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

    prompt = f"""You are an expert assistant for Material Safety Data Sheets.

Context from the knowledge base:
{context}

Answer the following question based on the context above.
If the context does not contain enough information, say so clearly.

Question: {question}"""

    messages.append(HumanMessage(content=prompt))
    response = llm.invoke(messages)
    return {"answer": response.content}
```

Two things to notice. First, `retrieve_node` is a deliberate stub — it returns a placeholder string. We build the real retrieval in Chapter 7; this stub lets us test the graph structure now without needing a live HANA connection. Second, `answer_node` builds the conversation history from the `messages` list in state. This is how multi-turn conversations work: the caller passes previous turns in the initial state, and the node includes them in the prompt.

---

## 6.5 Wiring the graph

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
        "question":    "What are the hazard codes for acetone?",
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
Based on the provided context, I don't have specific hazard codes for acetone.
The context contains a placeholder rather than actual MSDS data. Once the
knowledge base is populated with real MSDS documents, I will be able to
retrieve and report the specific GHS hazard codes for acetone.
```

The agent runs, reaches Vertex AI, and gives an honest answer about the stub context. That is the graph working correctly.

---

## 6.6 Adding a conditional retry edge

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

## 6.7 The StateGraph visualised

The graph we built in this chapter has three nodes and one conditional loop:

![LangGraph StateGraph Flow](docs/screenshots/diagrams/07-langgraph-state-graph.png)
*Figure 7.1: The simple Q&A agent's StateGraph — retrieve feeds answer, which feeds the check node. The check node either loops back to retrieve (on low-quality answers, up to 2 retries) or terminates at END. The dashed box on the right shows the AgentState structure that flows through every node.*

---

## 6.8 The complete simple_qa_agent.py

```python
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage, AIMessage

class AgentState(TypedDict):
    question:    str
    context:     str
    answer:      str
    messages:    List[dict]
    retry_count: int

llm = ChatVertexAI(model_name="gemini-1.5-pro", temperature=0.1, max_tokens=1024)

def retrieve_node(state: AgentState) -> dict:
    question = state["question"]
    return {"context": f"[Retrieved context for: {question}]"}

def answer_node(state: AgentState) -> dict:
    messages = []
    for msg in state.get("messages", []):
        cls = HumanMessage if msg["role"] == "user" else AIMessage
        messages.append(cls(content=msg["content"]))

    prompt = f"""You are an expert assistant for Material Safety Data Sheets.

Context:
{state['context']}

Question: {state['question']}
Answer:"""
    messages.append(HumanMessage(content=prompt))
    return {"answer": llm.invoke(messages).content}

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
        "question":    "What are the hazard codes for acetone?",
        "context":     "",
        "answer":      "",
        "messages":    [],
        "retry_count": 0,
    })
    print(result["answer"])
```

---

## 6.9 Tool use in LangGraph

LangGraph supports tools — Python functions that the LLM can choose to call. For the hybrid RAG agent, we will not use the LangGraph tool mechanism (we use direct parallel dispatch instead, as you will see in Chapter 7). But understanding tools is useful if you extend the agent later.

Define a tool with the `@tool` decorator:

```python
from langchain_core.tools import tool

@tool
def get_hazard_codes(material_number: str) -> str:
    """Retrieve GHS hazard codes for a material from the knowledge graph."""
    # In a real implementation this queries HANA SPARQL
    return "H225, H319, H336"
```

Bind tools to the LLM and use `ToolNode` for execution:

```python
from langgraph.prebuilt import ToolNode

tools = [get_hazard_codes]
llm_with_tools = llm.bind_tools(tools)
tool_node = ToolNode(tools)

graph.add_node("tools", tool_node)
graph.add_conditional_edges(
    "answer",
    lambda state: "tools" if state["messages"][-1].tool_calls else END,
    {"tools": "tools", END: END}
)
graph.add_edge("tools", "answer")
```

This creates a ReAct loop: the LLM decides whether to call a tool, the tool runs, and the result feeds back into the next LLM call.

> **Note:** Chapter 7 intentionally avoids this ReAct pattern for the main retrieval. We run both vector and KG chains on every query, regardless of what the LLM might choose. This gives deterministic latency and prevents the LLM from skipping a retrieval path it thinks is unnecessary.

---

## 6.10 Streaming responses

LangGraph can stream state updates as they happen. This is valuable when queries take several seconds — the user sees progress rather than a blank screen.

```python
for event in app.stream({
    "question":    "What first aid should I give if someone inhales acetone?",
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
  answer: If someone inhales acetone vapours, move them immediately to fresh air...
[check] completed
```

> **Tip:** In the FastAPI service, pipe the stream to a Server-Sent Events (SSE) response using `StreamingResponse`. The Fiori UI can consume the stream and update the chat interface progressively. We implement this in Chapter 9.

---

## 6.11 Debugging with LangSmith

LangSmith is LangChain's observability platform. It records every LangGraph run — inputs, outputs, intermediate states, LLM calls, latency, and token counts. It is free for individual developers.

Set three environment variables:

```bash
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
export LANGCHAIN_API_KEY=your-api-key-here
```

Get a free API key at `smith.langchain.com`. Once set, every `app.invoke()` and `app.stream()` call is automatically traced.

In your BTP CF `manifest.yml`, add the same variables:

```yaml
applications:
  - name: hybrid-rag-agent
    env:
      LANGCHAIN_TRACING_V2: "true"
      LANGCHAIN_ENDPOINT: "https://api.smith.langchain.com"
      LANGCHAIN_API_KEY: ((langchain-api-key))
```

Use a BTP User-Provided Service to supply the API key without storing it in the manifest. In the LangSmith dashboard you will see a tree view of each run: which nodes executed, in what order, how long each took, and the exact prompt sent to Gemini. When Chapter 7's parallel chains run, you will see two branches executing simultaneously.

> **Tip:** Tag your runs in `app.invoke(config={"metadata": {"material_number": material_number}})` and filter by `metadata.material_number` in LangSmith to see all queries against a specific document.

---

## 6.12 Why stateless works on BTP Cloud Foundry

A common concern when deploying LangGraph to Cloud Foundry is: what happens to agent state when you scale to multiple instances?

The answer is: nothing, because there is no server-side state to worry about.

LangGraph state is in-memory for a single request. When `app.invoke()` returns, the state is gone. There is no database, no session file, no sticky session required.

| Concern | Reality |
|---|---|
| CF runs 10 instances | Each request lands on any instance — fine |
| CF restarts an instance | No state is lost — state only exists during a request |
| Two users query simultaneously | Each gets their own independent in-memory state |
| Conversation history | Passed in `messages` field of every request body by the caller |

The conversation history pattern — where the client sends previous turns in every request — is the key. The frontend stores the last N messages and sends them with each new question.

```python
# Frontend sends history on every request
# POST /query
{
  "question": "And what about the flash point?",
  "material_number": "ACE001",
  "history": [
    {"role": "user",      "content": "What are the hazard codes for acetone?"},
    {"role": "assistant", "content": "The GHS hazard codes for acetone are H225, H319, and H336."}
  ]
}
```

The agent picks up the conversation exactly where it left off — without any server-side memory. This design is safe to scale horizontally on BTP CF without load balancer sticky sessions or shared caches.

---

## 6.13 Summary

In this chapter we built a LangGraph agent from scratch:

- Defined **state** as a `TypedDict` that flows through every node
- Wrote **nodes** as plain Python functions that read state and return partial updates
- Connected nodes with **edges** and **conditional edges** to express branching and looping
- Added a **retry loop** that re-runs retrieval when the answer quality is low
- Demonstrated **tool use** with the `@tool` decorator and `ToolNode`
- Enabled **streaming** to show node-level progress events
- Configured **LangSmith** for end-to-end observability
- Explained why **stateless design** makes LangGraph safe to scale horizontally on BTP CF

The agent built here uses a stub retriever. In Chapter 7, we replace that stub with the two HANA retrieval chains from Chapters 3 and 4 — and we run them in parallel.

---

## 6.14 Checkpoint

Before continuing to Chapter 7, verify the following:

```bash
# 1. LangGraph is installed
python -c "import langgraph; print(langgraph.__version__)"

# 2. The simple agent runs without errors
cd agents && python -m agents.simple_qa_agent

# 3. Vertex AI credentials are set
echo $GOOGLE_APPLICATION_CREDENTIALS   # should print a path to your JSON key

# 4. LangSmith (optional but recommended)
echo $LANGCHAIN_TRACING_V2             # should print "true"
```

If all four commands succeed, you have a working LangGraph agent connected to Vertex AI. Chapter 7 takes this foundation and builds the full parallel hybrid RAG system on top of it.

---

*End of Chapter 6*
