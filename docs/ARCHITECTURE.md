# Architectural Specification: Autonomous Multi-Agent Triad

## 1. System Topology & Communication

```
+-------------------------------------------------------------------------+
|                               Antigravity                               |
|              (Executive Engine / High-Context Shield / CLI)             |
+------------------------------------+------------------------------------+
                                     |
           +-------------------------+-------------------------+
           |                                                   |
           v                                                   v
+------------------------+                           +--------------------+
|  Advisory Council      |                           |   Hermes Agent     |
|  - Claude Code (Pro)   |                           |   - Android Relay  |
|  - OpenAI Codex (Plus) |                           |   - Nous Portal    |
+------------------------+                           +--------------------+
           |                                                   |
           v                                                   v
+------------------------+                           +--------------------+
| Local Ground Truth     |                           | Local Memory Hub   |
| - tsc --noEmit         |                           | - PiecesOS (:39300)|
| - Vitest / Jest Suites |                           | - Mem0 Semantic DB |
+------------------------+                           +--------------------+
```

## 2. Invariant Rules

1. **Context Shielding:**
   Antigravity must ingest raw build logs, git logs, and expansive multi-file contexts up to 2M tokens. When consulting Claude Code or OpenAI Codex, queries must be minimal, distilled, and focused on architectural decisions or diff reviews to conserve the 5-hour rolling session limit.

2. **Zero-Token MCP Stripping:**
   Local CLI invocations of `claude` and `codex` must bypass local MCP configs by supplying an empty configuration (`empty-mcp.json`) and `--ignore-user-config`. This avoids injecting 370+ tools and reduces token usage from ~304,000 tokens to under ~500 tokens.

3. **High-Availability Zero-Downtime Failover:**
   When Claude Code returns a session limit or error, the bridge automatically routes the identical prompt to OpenAI Codex (`gpt-6-astra`), returning an authoritative response without user intervention.

4. **Zero Incremental Cost:**
   No metered API tokens are used. Only existing flat-rate subscriptions (Claude Pro, ChatGPT Plus) and free/local services (Nous free portal, PiecesOS, Ollama) are utilized.

## 3. Unified Intent Engine & Autonomous Routing

The Triad includes a deterministic, zero-latency Intent Engine (`triad/intent_engine.py`) executing in <1ms without token burn:

```
                      +-----------------------+
                      | Raw Developer Request |
                      +-----------+-----------+
                                  |
                                  v
                  +-------------------------------+
                  |  Deterministic Classifier     |
                  |  (Regex & Subsystem Heuristics|
                  +---------------+---------------+
                                  |
            +---------------------+---------------------+
            |                     |                     |
            v                     v                     v
   [REVIEW / GATE / DBG]       [DEVICE]              [MEMORY]
            |                     |                     |
     High Stakes?                 v                     v
     /        \             Hermes Agent           PiecesOS (:39300)
    v          v             (:8766 Bridge)        + Mem0 Semantic DB
[Claude/Codex] [Dual-Council
  Advisory]      Competition]
```

### Classification Categories:
1. **REVIEW:** Unified diffs, git patches, or pull requests -> routes to `cmd_review`.
2. **GATE:** Pre-commit verifications, typecheck, or test passes -> routes to `cmd_gate`.
3. **DEBUG:** Stack traces (Python, JS/TS, Kotlin/Java, Rust, Go) or compiler outputs -> routes to `cmd_debug`.
4. **DEVICE:** Mobile automation, SMS, notification, or Android relay triggers -> routes to Hermes Agent (`:8766`).
5. **MEMORY:** Retrospective queries ("what did I do yesterday...") -> queries PiecesOS (`:39300`) and Mem0.
6. **DOCTOR:** Health checks, audits, subscriptions, ports -> routes to `cmd_doctor`.
7. **ARCHITECT / GENERAL:** System design, tradeoffs, schema design -> routes to `cmd_consult`.

### High-Stakes Auto-Adjudication:
When intent classification detects high-risk architectural concerns (auth, cryptography, JWT, database migrations, RLS, payment gateways, concurrency/deadlocks), it automatically promotes the query to **Competition Mode**, launching Claude Code and OpenAI Codex in parallel and synthesizing their verdicts via an automated impartial adjudicator.
