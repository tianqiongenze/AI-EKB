# Architecture Evaluation: 10B Global Users / 1M Concurrent Connections

## Current State Assessment
The current platform uses an enterprise-grade stack:
- **TiDB:** Distributed NewSQL database.
- **Pulsar:** High-performance, scalable messaging and event streaming.
- **Milvus:** Distributed vector database for similarity search.
- **Neo4j:** Graph database for knowledge relationships.
- **Redis:** High-speed in-memory data store for caching and rate limiting.

### The Bottleneck
The Python control plane (`src/enterprise_ekb/app.py`), serving as the primary entry point via FastAPI, is not inherently designed to handle **1 million concurrent WebSocket/SSE connections** or simple REST requests efficiently under such extreme loads. While TiDB and Pulsar can scale horizontally, running millions of connections through Python worker processes (e.g., Uvicorn/Gunicorn) would require a massive and inefficient compute footprint due to the GIL and single-threaded event loops.

## Recommended Target Architecture

To support **10 billion registered users** and **1 million concurrent connections** globally, the architecture must evolve to a geo-distributed topology with an edge-optimized edge/gateway layer.

### 1. Global Geo-Distribution (Active-Active)
- **Multi-Region Deployments:** Deploy fully replicated environments across at least 3 global regions (e.g., US-East, EU-Central, AP-Northeast).
- **Global DNS & Anycast:** Route users to the nearest regional PoP (Point of Presence) using AWS Global Accelerator or Cloudflare.

### 2. The Go/Rust Connection Gateway
- **Connection Offloading:** Replace or front the Python API with a highly concurrent Go or Rust gateway (e.g., using `gorilla/websocket` or a standard Go `net/http` server with Epoll/Kqueue optimizations). Go's lightweight goroutines are uniquely suited for maintaining millions of long-lived concurrent TCP connections (WebSockets/SSE) with minimal memory overhead.
- **Stateless Routing:** The Go gateway terminates the connection, validates the JWT, and proxies intent-based requests to the Python control plane or publishes directly to Pulsar topics.

### 3. Data Tier Sharding
- **TiDB Scaling:** TiDB already separates compute (TiDB nodes) and storage (TiKV nodes). For 10B users, configure Placement Rules in TiKV to pin user data to their respective geographical regions (Data Residency/Sovereignty compliance).
- **Redis Clusters:** Use Redis Cluster topology at each edge location to manage session state, rate limiting, and local pub/sub for chat state.

### 4. Advanced Multi-Agent Orchestration (Sub-Agents)
To support massive scale agentic workflows, the system has now been upgraded with a formal **Sub-Agent Delegation Standard (Supervisor/Worker pattern)**.
- **Design:** Instead of relying on monolithic synchronous agents, complex intents are broken down by a `Supervisor` agent and delegated asynchronously via the new `/a2a/sub-agent/delegate` API.
- **Execution:** Requests enqueue `a2a.message` events targeting specific sub-agent types (e.g., `analyst`, `coder`). 
- **Scale Impact:** This prevents blocking HTTP threads. Workers consume tasks from Pulsar horizontally, allowing near-infinite scaling of background LLM inference and tool usage.

## Conclusion
The underlying storage and event buses (TiDB, Pulsar, Milvus) are already positioned for 10B/1M scale. However, the connection termination layer must be offloaded to a compiled language (Go/Rust), and agentic workflows must strictly utilize the newly implemented asynchronous Sub-Agent delegation pattern to prevent control-plane starvation.
