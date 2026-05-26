"""
agents/agents/simple_qa_agent.py
Book reference: Chapter 7 — LangGraph Fundamentals

Simple LangGraph Q&A agent — Chapter 7.

Uses a stub retriever so the graph structure can be tested without a live
HANA connection.  Chapter 8 replaces retrieve_node with the real vector +
KG chains.
"""
from typing import TypedDict, List

from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage


# ── State ──────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    question:    str
    context:     str
    answer:      str
    messages:    List[dict]
    retry_count: int


# ── Lazy LLM getter ────────────────────────────────────────────────────────────

def _get_llm() -> ChatGoogleGenerativeAI:
    """Return a ChatGoogleGenerativeAI instance (instantiated on first call)."""
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-preview-05-20",
        temperature=0.1,
        max_tokens=1024,
    )


# ── Nodes ──────────────────────────────────────────────────────────────────────

def retrieve_node(state: AgentState) -> dict:
    """Stub retriever — replaced by vector + KG chains in Chapter 8."""
    question = state["question"]
    return {"context": f"[Retrieved context for: {question}]"}


def answer_node(state: AgentState) -> dict:
    """Generate an answer using the retrieved context."""
    messages = []
    for msg in state.get("messages", []):
        cls = HumanMessage if msg["role"] == "user" else AIMessage
        messages.append(cls(content=msg["content"]))

    prompt = f"""You are an expert assistant for Material Safety Data Sheets.

Context from the knowledge base:
{state['context']}

Answer the following question based on the context above.
If the context does not contain enough information, say so clearly.

Question: {state['question']}
Answer:"""

    messages.append(HumanMessage(content=prompt))
    return {"answer": _get_llm().invoke(messages).content}


def check_answer_node(state: AgentState) -> dict:
    """Check if the answer is acceptable. Increment retry counter if not."""
    low = [
        "don't have", "no information", "cannot find",
        "not available", "placeholder",
    ]
    needs_retry = any(p in state.get("answer", "").lower() for p in low)
    return {"retry_count": state.get("retry_count", 0) + (1 if needs_retry else 0)}


def route_after_check(state: AgentState) -> str:
    """Decide whether to retry or finish."""
    low = [
        "don't have", "no information", "cannot find",
        "not available", "placeholder",
    ]
    needs_retry = any(p in state.get("answer", "").lower() for p in low)
    return "retry" if (needs_retry and state.get("retry_count", 0) < 2) else "done"


# ── Graph construction ─────────────────────────────────────────────────────────

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
        {"retry": "retrieve", "done": END},
    )

    return graph.compile()


app = build_graph()


# ── CLI smoke test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = app.invoke({
        "question":    "What are the hazard codes for acetone?",
        "context":     "",
        "answer":      "",
        "messages":    [],
        "retry_count": 0,
    })
    print(result["answer"])
