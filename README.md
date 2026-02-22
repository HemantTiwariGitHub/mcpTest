# Simple MCP Learning Project (Python + SQL)

This project is a minimal learning setup that includes:

- A **SQLite database** initialized from SQL.
- A **simple MCP server** (JSON-RPC over stdio with MCP-style methods).
- A **small agent/client** that connects to the MCP server, calls tools, and prints results.

## Project structure

- `database/schema.sql` — SQL schema for the SQLite database.
- `server/mcp_server.py` — MCP server exposing `add_todo` and `list_todos` tools.
- `agent/mcp_agent_client.py` — Tiny MCP client/agent that starts server and interacts with it.

## Requirements

- Python 3.10+
- No external dependencies (uses Python standard library + SQLite)

## Run the learning demo

```bash
python agent/mcp_agent_client.py
```

You should see output showing:
1. MCP initialize response
2. Available tools
3. A new todo inserted into SQLite
4. Current todo list returned by the server

## Notes

- The transport uses `Content-Length` framed JSON-RPC messages over stdio.
- This is intentionally small and educational, not production-ready.
