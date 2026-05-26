# Chapter 1: Welcome to the Agentic Era

There is a particular moment in every technology cycle when the language we use to describe the work changes. We stop talking about "models" and start talking about "agents." We stop asking "what can it generate?" and start asking "what can it do?" We stop measuring tokens per second and start measuring tasks per hour. That moment, for enterprise AI, has arrived.

If you are reading this book, you have probably already noticed the shift. Your inbox is full of vendor pitches for "agentic platforms." Your colleagues are forwarding LinkedIn posts about autonomous workflows. Your CTO has asked, in a meeting that ran fifteen minutes too long, whether the team has a strategy for "AI agents." And underneath all of that noise, you have a quieter, more pragmatic question: *What does this actually mean for the systems I build, and how do I build one that works?*

This book is an answer to that question. Over the next several chapters, we will build, end to end, a working agentic system that solves a real enterprise problem on SAP Business Technology Platform (SAP BTP) and Google Cloud. But before we touch a single line of code, we need to agree on what we are building and why. That is the work of this chapter.

## 1.1 From Models That Answer to Systems That Act

A useful way to understand the agentic era is to remember what it replaced.

For most of the last decade, building anything intelligent into an enterprise application meant assembling a small army. You needed data engineers to clean and pipe the training data, data scientists to choose and tune a model, ML engineers to package the artifact, and platform engineers to deploy it behind an API. Each model solved exactly one problem — classifying invoices, forecasting demand, recommending products — and each new problem demanded a new project, a new dataset, and a new round of training. The barrier to entry was high, the time to value was long, and the resulting models were brittle in the ways that custom ML is always brittle: a small shift in input distribution and the predictions quietly drifted off the rails.

Foundation models changed the economics. A single API call to a large language model could now classify, summarize, extract, translate, draft, and explain — without any training, without any infrastructure, without any of the traditional ML lifecycle. For application developers, this was liberating. For the first time, a feature that would once have required a six-month project could be prototyped in an afternoon.

But there was a catch, and anyone who built a serious feature on top of a raw LLM eventually ran into it. A foundation model, however capable, is fundamentally *passive*. It receives a prompt and returns a completion. It does not look up data it does not already have. It does not call your APIs. It does not check whether its answer is true. It does not stop and think when it is uncertain. It does not remember what you told it ten minutes ago. It produces fluent text on demand, and that is both its strength and its limit.

The agentic leap is the move from passive completion to active reasoning. An agent is what you get when you take a foundation model and surround it with the missing pieces: tools it can call, memory it can read and write, plans it can construct and revise, and a loop that keeps running until a goal is met. The model becomes the reasoning engine; the surrounding system gives it hands, eyes, and a sense of purpose.

The clearest test of whether a system is genuinely agentic is the one Michael Albada offers in *Building Applications with AI Agents*: does it demonstrate real decision making, or is it following a static script? A workflow that always retrieves three documents, always passes them to the same prompt, and always returns the model's first response is not an agent. It is a deterministic pipeline with an LLM somewhere in the middle. An agent, by contrast, decides — at runtime, based on what it sees — whether to retrieve more, whether to ask a clarifying question, whether to invoke a different tool, or whether to stop and admit it does not know.

That distinction matters because it changes what we have to design for. With a deterministic pipeline, the engineering problem is mostly about plumbing. With an agent, the engineering problem is about *behavior under uncertainty*: how the system reasons, when it acts, what it can be trusted to do without supervision, and how we observe and correct it when it goes wrong.

## 1.2 A Spectrum, Not a Switch

It is tempting to treat "agent" as a binary label — either a system is one or it is not. In practice, the more honest picture is a spectrum, and most enterprise systems live somewhere in the middle of it.

At one end is traditional code: deterministic, explainable, fast, and incapable of handling anything its author did not anticipate. A SQL query is at this end of the spectrum.

A step further along is the deterministic LLM workflow. The structure is fixed — retrieve, prompt, return — but the model contributes flexibility within each step. A summarization service that always reads the same field from the same record and always asks the model for the same kind of summary is a deterministic workflow.

Further still is retrieval-augmented generation, or RAG. Here the system grounds the model in external knowledge: the user asks a question, the system retrieves relevant documents, the model answers using those documents as context. RAG is where most production "AI assistants" live today. It is more flexible than a static workflow because the retrieval step adapts to the question, but the control flow is still essentially fixed.

At the far end of the spectrum is the autonomous agent: a system that decides which tools to call, in what order, and when to stop, often invoking the model multiple times in a single turn to plan, act, observe, and replan. Autonomous agents are the most adaptable systems we know how to build, but they pay for that adaptability in latency, cost, and explainability. Every additional reasoning step is another LLM call, another opportunity for the model to wander off course, another thing the auditor will want to see traced.

The system we build in this book sits deliberately in the middle of this spectrum. It is more than a fixed RAG pipeline — it makes runtime decisions about which retrieval strategy to use and how to combine the results — but it is less than a fully autonomous agent. We will call it an *agentic RAG* system, and the choice to stay in the middle is intentional. For the kind of enterprise problem we are solving, the middle of the spectrum is where the trust, the cost, and the capability all balance.

The table below sketches how these four points compare on the dimensions that matter for enterprise deployment.

| Dimension       | Traditional Code | Deterministic LLM Workflow | RAG System          | Agentic RAG (this book) | Autonomous Agent     |
| --------------- | ---------------- | -------------------------- | ------------------- | ----------------------- | -------------------- |
| Input structure | Strict schema    | Mostly structured          | Natural language    | Natural language        | Natural language     |
| Adaptability    | None             | Low                        | Medium              | Medium-high             | High                 |
| Explainability  | High             | High                       | High                | High                    | Lower                |
| Latency         | Milliseconds     | Seconds                    | Seconds             | Seconds                 | Tens of seconds      |
| Failure mode    | Hard error       | Wrong but consistent       | Plausible but stale | Honest "I don't know"   | Confidently off-task |

The last row is the one that matters most for the enterprise. A system that fails loudly, predictably, and honestly is far more useful than one that fails in confident, fluent prose.

## 1.3 The Trouble With General-Purpose Assistants

Most of the AI assistants the public has met so far are general-purpose. They are designed to answer almost anything, to anyone, in any context. That generality is a remarkable engineering achievement, and it makes for an excellent demo. It also makes them the wrong shape for most enterprise problems.

Consider a question that any chemical safety officer might reasonably ask of an internal assistant: *"What is the GHS hazard classification for acetone?"*

A general-purpose assistant will produce a fluent, confident answer. The answer will probably be correct, because acetone is well-documented in the public corpus the model was trained on. But the assistant cannot tell you *which version* of the GHS revision its answer reflects, *which jurisdiction* it applies to, or *whether your company's own safety data sheet for acetone* — the document that actually governs your operations — agrees with what it just told you. If the public corpus is six months out of date, or if your supplier has issued a revised data sheet, the assistant will not know, and it will not say so. It will simply produce its best guess, indistinguishable in tone from a verified fact.

In a casual context, this is fine. In a regulated context, it is the kind of problem that ends careers. "Plausible-sounding" is not the standard a manufacturing safety system can be held to. The standard is *verifiable*, *structured*, and *traceable to a source*.

This is the gap that domain-specific agents exist to close. Albada categorizes agents into several types in *Building Applications with AI Agents* — business-task agents, conversational agents, research agents, analytics agents, developer agents, browser-using agents — but the one we care about most in this book is the domain-specific agent. In his words, these are agents "tuned for specialized professional domains, such as legal (Harvey), medical (Hippocratic AI), or finance agents," combining "domain-specific knowledge with structured workflows to deliver targeted, expert-level assistance."

The defining characteristic of a domain-specific agent is not that it knows more than a general assistant. It is that it knows *less, but better*. It operates within a bounded knowledge domain — your documents, your ontology, your facts — and it refuses to step outside that boundary. When asked about acetone, a well-built domain-specific MSDS agent will not lean on a half-remembered training-data tidbit. It will retrieve the actual safety data sheet your company maintains for acetone, cite the section it drew from, and tell you when the document was last revised. If the document does not contain the answer, the agent says so. That last part — the willingness to say "I don't have that information" — is the single feature that most distinguishes a trustworthy enterprise agent from a hallucinating chatbot.

There are three properties that make domain-specific agents the right shape for enterprise work, and each will reappear throughout this book.

The first is **bounded knowledge**. The agent's universe is the corpus you give it, plus the structured facts you have curated. It does not invent codes, classifications, or part numbers because it has no source for invented ones. It can be wrong, but only in ways that trace back to a real document.

The second is **structured plus semantic retrieval**. Some questions are best answered by a precise lookup against structured data — "what is the GHS code for acetone?" is one of them. Other questions are best answered by finding semantically similar passages in unstructured prose — "what should I do if a worker spills acetone on bare skin?" is one of those. A domain-specific agent uses both.

The third is **auditability**. Every answer the agent produces can be traced to a specific document chunk or a specific knowledge-graph triple. The auditor can ask "where did this come from?" and get an honest, specific answer. In a regulated industry, this is not a nice-to-have. It is the price of admission.

> **Note:** Domain-specific does not mean small. Harvey serves global law firms; Hippocratic AI is deployed across major hospital systems. The boundary is not on capacity but on scope: these agents are deep in one domain rather than shallow across many. Depth is what makes them trustworthy.

## 1.4 Why Hybrid Retrieval Is the Right Engine

Once you accept that a domain-specific agent should retrieve before it generates, the next question is *how* it should retrieve. This is where most architectures take a wrong turn.

The default answer in 2024 and early 2025 was: vector search, full stop. Embed your documents, store the vectors, and at query time embed the question and find the nearest chunks. Vector search is genuinely powerful. It is forgiving — a question phrased one way will retrieve a passage phrased another way, because both map to similar regions of embedding space. It handles natural language gracefully. It is fast at scale. For a long stretch, it looked like the universal retrieval primitive.

But anyone who has tried to build a real domain-specific assistant on vector search alone has run into the same wall: vector search is bad at facts. Asked for the GHS hazard classification of acetone, a vector search will return a chunk that *talks about* acetone and hazard classifications, but the agent then has to read prose and extract a code. Sometimes the model extracts correctly. Sometimes it mixes up acetone with a similarly-named solvent that appeared in the same document. Sometimes the relevant chunk did not get retrieved at all because the question phrasing was too terse to embed well. For narrative reasoning, vector search is excellent. For symbolic facts, it is the wrong tool.

The complementary tool is the knowledge graph. A knowledge graph stores facts as triples — *(acetone, hasGHSClassification, H225)* — and answers questions by traversing relationships rather than by similarity. Asked the same hazard-classification question, a graph-backed retrieval returns the exact code, with a citation to the document that asserted it. The graph cannot hallucinate a classification it has never been told, because it does not generate; it looks up. For symbolic facts, this is exactly the property we want.

Neither retrieval strategy alone is enough. Vector search wins on fuzzy, narrative, semantic questions. Knowledge graphs win on precise, structured, symbolic questions. A real enterprise corpus contains both kinds of content, and a real user asks both kinds of questions, often in the same conversation.

Hybrid RAG runs both retrieval strategies in parallel and lets the agent decide what to do with the results. The decision logic is simpler than it sounds.

When both retrievals return relevant content, the agent synthesizes — using the graph to anchor the structured facts and the vector results to flesh out the narrative context. The user gets an answer that is both precise and readable.

When only one retrieval returns relevant content, the agent uses that one directly. A pure factual question may need only the graph. A pure narrative question may need only the vectors.

When neither retrieval returns relevant content, the agent says so. This is the moment that separates trustworthy systems from theatrical ones. A general assistant will fall back on its training data and produce a confident guess. A well-built hybrid agent will say "I don't have that in my sources" and stop.

This pattern — graph plus vectors, parallel retrieval, honest fallback — is the architectural spine of every system we build in this book. It is also, not coincidentally, the architecture that SAP itself is converging on for its agentic infrastructure, for the same reasons we have just walked through.

## 1.5 What We Will Build

The running example for the rest of the book is a domain-specific agent for **Material Safety Data Sheets**, or MSDS. If you have not encountered MSDS documents before, they are the regulatory artifacts that govern how chemical substances are handled, stored, transported, and disposed of. Every manufacturer, pharmaceutical company, chemical processor, and laboratory on Earth maintains a library of them. Most of those libraries live as PDFs in shared drives, with metadata in spreadsheets, and the people who actually need answers — operators on a shop floor, technicians in a warehouse, a nurse responding to a spill — typically cannot find the information they need fast enough to act on it.

MSDS documents are an almost unfair example for hybrid RAG, because they contain both kinds of content in equal measure. On one page, you will find dense narrative prose: how to ventilate a room after a spill, what the first-aid steps are for skin contact, how to dispose of contaminated absorbent material. On the next page, you will find precise structured data: GHS hazard codes, signal words, exposure limits, flash points, classification categories. The narrative pages are perfect for vector search. The structured pages are perfect for a knowledge graph. A real user — say, a safety officer responding to a question from the shop floor — will mix questions about both, often in a single sentence.

Over the course of this book we will build a system that does the following.

It ingests MSDS PDFs end to end, automatically extracting both the prose passages and the structured facts. The prose passages are chunked, embedded with a vector model, and stored in SAP HANA Cloud's vector engine. The structured facts are extracted into RDF triples and stored in HANA's graph engine. The same document populates both stores in a single ingestion run.

It answers questions using both retrieval strategies in parallel. A FastAPI service orchestrated with LangGraph runs the graph query and the vector search at the same time, gathers the results, and routes them through Gemini 2.5 Flash on Vertex AI for synthesis. The agent decides, per query, whether to use one retrieval, both, or neither.

It exposes the answers through a CAP Node.js OData V4 service with a Fiori Elements user interface, so a safety officer can ask a question from a familiar SAP-style screen and see a cited, structured response.

It runs entirely on the SAP BTP free trial and the Google Cloud Platform $300 free credit. There is no paid step in the build. By the end of the book, you will have a working system, deployed to a real cloud, that you built without spending a dollar.

The architecture, the patterns, and the engineering choices we make along the way generalize far beyond MSDS. Substitute legal contracts for safety data sheets and you have the skeleton of a Harvey-style legal agent. Substitute clinical guidelines and you have something that looks a lot like Hippocratic AI. Substitute equipment maintenance manuals and you have a field-service agent. The domain changes. The pattern does not.

## 1.6 Why This Moment, and Why for SAP Developers

In May 2026, at SAP Sapphire, SAP announced more than two hundred specialized Joule agents shipping across the application portfolio over the following year. Read carefully, that is not an announcement of two hundred general-purpose chatbots. It is an announcement of two hundred *domain-specific agents* — for finance close, for procurement, for HR transactions, for supply-chain exceptions, for sustainability reporting. SAP has bet the next chapter of its product strategy on the same pattern this book teaches.

That is not a coincidence, and it is not marketing. It is what happens when a company with the deepest enterprise data graph in the world looks at the agentic landscape and asks which patterns will actually work inside its customers' regulated, audited, mission-critical processes. The answer is the answer this book has been making the case for: bounded domains, hybrid retrieval, traceable answers, and a refusal to hallucinate.

For an SAP developer, this is the most interesting moment your career has handed you so far. The skills required to build these agents — vector search, knowledge graphs, LangGraph orchestration, CAP integration, BTP deployment, Document grounding — are not yet common. They are exactly the skills SAP itself is hiring for, that SAP partners are bidding on, and that SAP customers are about to need at scale. The patterns are early enough to learn, and important enough to be worth learning.

The chapters that follow are designed to make that learning concrete. We will not stay in the conceptual register much longer. By the end of Chapter 3, you will be running working code against a real HANA Cloud vector index. By the end of the book, you will have shipped a domain-specific MSDS agent with both retrieval engines, a real UI, and a real deployment.

## 1.7 Summary

The agentic era is not a marketing slogan; it is a real shift in what software can do. Foundation models gave us systems that could understand language. Tools, memory, and planning give us systems that can act on it. The transition from passive completion to active reasoning is the one engineering shift that matters most for enterprise applications over the next several years.

General-purpose assistants are impressive demos, but they are the wrong shape for regulated, high-stakes enterprise work. Domain-specific agents — bounded in scope, deep in knowledge, auditable in operation — are the shape that fits.

The retrieval engine that makes domain-specific agents trustworthy is hybrid. Vector search alone fails on facts. Knowledge graphs alone fail on narrative. Run both in parallel, synthesize when both return, defer to whichever returns when only one does, and admit ignorance when neither does. That is the architecture we will build.

The system we build to make this concrete is an MSDS agent — a domain-specific assistant for safety data sheets that runs on SAP HANA Cloud, LangGraph, and Vertex AI, exposed through a CAP service and a Fiori UI, deployed entirely on free tiers.

In Chapter 2, we examine why SAP developers are uniquely positioned to build these systems — and set up the platform we will use throughout the rest of the book.

> **Note:** The framework for thinking about agent types in this chapter draws on Michael Albada's *Building Applications with AI Agents* (O'Reilly, 2026), which provides an excellent taxonomy of agentic systems. Our focus on domain-specific agents builds directly on that foundation.
