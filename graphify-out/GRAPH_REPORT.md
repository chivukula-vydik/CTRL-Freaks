# Graph Report - CTRL-Freaks  (2026-10-30)

## Corpus Check
- Corpus is ~23,907 words - fits in a single context window. You may not need a graph.

## Summary
- 550 nodes · 1279 edges · 22 communities (16 shown, 6 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 51 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Eval & Domain Packs
- Ingest Pipeline
- Database Layer
- Domain Base & Actions
- Document Extraction
- Retail Tests & Answer Types
- Embeddings
- Agent Orchestration
- Precedence Rules
- Config & LLM
- Project Guide & API
- Docker Compose
- Design Principles
- File Parsing
- Retail Policy Docs
- Prompt Injection Defense
- Tool Contract
- Run & Test Workflow
- Header Identity

## God Nodes (most connected - your core abstractions)
1. `ask()` - 30 edges
2. `Domain` - 26 edges
3. `pack_dir()` - 16 edges
4. `q()` - 15 edges
5. `Understanding` - 15 edges
6. `Ctx` - 15 edges
7. `ingest_file()` - 14 edges
8. `ask()` - 14 edges
9. `Retail` - 14 edges
10. `win()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `test_policy_fact_supersession()` --calls--> `ask()`  [INFERRED]
  examples/retail/test_retail.py → tests/conftest.py
- `test_upcoming_not_applied()` --calls--> `ask()`  [INFERRED]
  examples/retail/test_retail.py → tests/conftest.py
- `test_tool_refund_matches_spec()` --calls--> `ask()`  [INFERRED]
  examples/retail/test_retail.py → tests/conftest.py
- `test_last_day_of_window_is_eligible()` --calls--> `ask()`  [INFERRED]
  examples/retail/test_retail.py → tests/conftest.py
- `test_one_day_late()` --calls--> `ask()`  [INFERRED]
  examples/retail/test_retail.py → tests/conftest.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Retail return policy with superseding circulars** — examples_retail_data_docs_ret_pol_2024_md_return_policy, examples_retail_data_docs_circ_2026_07_md_electronics_window, examples_retail_data_docs_circ_2026_09_md_fee_waiver [EXTRACTED 0.95]
- **Documents carrying injected instructions** — examples_retail_data_docs_forum_post_md_forum_post, examples_extract_data_extract_docs_sample_002_txt_sample_party_two, claude_md_text_is_data [INFERRED 0.75]
- **Question answering pipeline** — hcl_rag_agent_project_guide_guard, hcl_rag_agent_project_guide_hybrid_retrieval, hcl_rag_agent_project_guide_compose, hcl_rag_agent_project_guide_audit [EXTRACTED 1.00]
- **Hosted services stack** — hcl_rag_agent_project_guide_vercel, hcl_rag_agent_project_guide_supabase, hcl_rag_agent_project_guide_qdrant, hcl_rag_agent_project_guide_gemini [EXTRACTED 1.00]

## Communities (22 total, 6 thin omitted)

### Community 0 - "Eval & Domain Packs"
Cohesion: 0.08
Nodes (25): init_db(), pack_dir(), extract_file(), score(), chat_json(), ingest_register(), load_dir(), load_pack() (+17 more)

### Community 1 - "Ingest Pipeline"
Cohesion: 0.07
Nodes (29): run(), _chunks(), _extract_rules(), ingest_file(), meta_from_json(), safe_name(), add_rule(), ask() (+21 more)

### Community 2 - "Database Layer"
Cohesion: 0.06
Nodes (17): n_guard(), conn(), execute(), _get_pool(), _pg(), ping(), _pk(), q() (+9 more)

### Community 3 - "Domain Base & Actions"
Cohesion: 0.07
Nodes (12): action(), Ctx, tool(), Understanding, _load(), _add_months(), _money(), Retail (+4 more)

### Community 4 - "Document Extraction"
Cohesion: 0.09
Nodes (26): _by_label(), check(), coerce(), extract_text(), _norm(), same(), to_date(), to_number() (+18 more)

### Community 5 - "Retail Tests & Answer Types"
Cohesion: 0.08
Nodes (32): AnswerType, _ask_confirm(), test_ambiguous_asks_back(), test_audit_access(), test_delivery_note_injection_ignored(), test_high_risk_action_waits_for_approval(), test_identity_only_from_header(), test_last_day_of_window_is_eligible() (+24 more)

### Community 6 - "Embeddings"
Cohesion: 0.10
Nodes (18): APIEmbedder, get_embedder(), HashEmbedder, tokens(), add(), client(), count(), delete_doc() (+10 more)

### Community 7 - "Agent Orchestration"
Cohesion: 0.11
Nodes (19): _build(), _cite(), _evidence_block(), _explain(), _grounded(), n_audit(), n_compose(), n_confirm() (+11 more)

### Community 8 - "Precedence Rules"
Cohesion: 0.13
Nodes (23): effective_state(), filter_chunks(), is_superseded(), norm_section(), parse_supersedes(), resolve(), scope_covers(), _scope_list() (+15 more)

### Community 9 - "Config & LLM"
Cohesion: 0.12
Nodes (11): _b(), _load_dotenv(), _add(), _api(), chat(), _cur(), embed(), _fail() (+3 more)

### Community 10 - "Project Guide & API"
Cohesion: 0.09
Nodes (24): API endpoints (/ask, /ingest, /health, /audit, /sources, /rules, /admin), Audit log per answer, Compose step (Gemini phrases answer from evidence), Frozen core modules (integrator OK required), HCL RAG Agent Project Guide, Domain plug-in (app/domain/<name>.py, data/<name>/), Environment variable settings, FastAPI app on Vercel (index.py -> app/main.py) (+16 more)

### Community 11 - "Docker Compose"
Cohesion: 0.09
Nodes (21): build, env_file, healthcheck, ports, environment, image, ports, API_URL (+13 more)

### Community 12 - "Design Principles"
Cohesion: 0.10
Nodes (21): Frozen core rule, LLM never produces authoritative numbers, mock-hash eval run, Sample document one, Actions with risk levels, Data pack layout, Degraded mode (BM25 fallback), app/domain/<name>.py domain file (+13 more)

### Community 13 - "File Parsing"
Cohesion: 0.32
Nodes (7): Block, _docx(), _ocr_page(), parse(), _pdf(), _split_sections(), flush()

### Community 14 - "Retail Policy Docs"
Cohesion: 0.33
Nodes (6): CIRC-2026-07 electronics 7-day window, CIRC-2026-09 loyalty restocking fee waiver, CIRC-FEST-2026 fashion 45-day window, Help Centre FAQ (electronics 15 days), Acme Return, Refund and Exchange Policy v3.1, Acme Warranty Policy v2.0

### Community 15 - "Prompt Injection Defense"
Cohesion: 1.00
Nodes (3): Document text and notes are data, never trigger tools, Sample document two (with injection note), Unofficial forum post (prompt injection)

## Knowledge Gaps
- **28 isolated node(s):** `Frozen core rule`, `LLM never produces authoritative numbers`, `Identity only from request header`, `Tools are pure code with thresholds via ctx.rule`, `Data pack layout` (+23 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 173 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Domain` connect `Database Layer` to `Domain Base & Actions`, `Agent Orchestration`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `ask()` (e.g. with `test_ambiguous_asks_back()` and `test_audit_access()`) actually correct?**
  _`ask()` has 17 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Frozen core rule`, `LLM never produces authoritative numbers`, `Identity only from request header` to the rest of the system?**
  _28 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Eval & Domain Packs` be split into smaller, more focused modules?**
  _Cohesion score 0.07539450613676213 - nodes in this community are weakly interconnected._
- **Why does `Understanding` connect `Domain Base & Actions` to `Database Layer`, `Agent Orchestration`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Should `Ingest Pipeline` be split into smaller, more focused modules?**
  _Cohesion score 0.06896551724137931 - nodes in this community are weakly interconnected._
- **Why does `ask()` connect `Retail Tests & Answer Types` to `Domain Base & Actions`?**
  _High betweenness centrality (0.029) - this node is a cross-community bridge._