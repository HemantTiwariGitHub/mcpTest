#!/usr/bin/env python3
"""Small MCP client/agent for learning.

Starts the local MCP server subprocess and demonstrates:
1) initialize
2) tools/list
3) tools/call (add_todo)
4) tools/call (list_todos)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "server" / "mcp_server.py"


class MCPClient:
    def __init__(self, command: list[str]) -> None:
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._request_id = 0

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=2)

    def _write_message(self, payload: dict[str, Any]) -> None:
        if self.proc.stdin is None:
            raise RuntimeError("stdin is not available")
        body = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        self.proc.stdin.write(header)
        self.proc.stdin.write(body)
        self.proc.stdin.flush()

    def _read_message(self) -> dict[str, Any]:
        if self.proc.stdout is None:
            raise RuntimeError("stdout is not available")

        headers: dict[str, str] = {}
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("Server closed stdout unexpectedly")
            decoded = line.decode("utf-8").strip()
            if decoded == "":
                break
            key, value = decoded.split(":", 1)
            headers[key.strip().lower()] = value.strip()

        length = int(headers.get("content-length", "0"))
        if length <= 0:
            raise RuntimeError("Invalid Content-Length")

        body = self.proc.stdout.read(length)
        return json.loads(body.decode("utf-8"))

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        self._write_message(payload)
        response = self._read_message()
        if "error" in response:
            raise RuntimeError(f"MCP error: {response['error']}")
        return response["result"]


def pretty(title: str, data: Any) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(data, indent=2))


def run_learning_agent() -> None:
    client = MCPClient([sys.executable, str(SERVER_PATH)])
    try:
        init_result = client.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "learning-agent", "version": "0.1.0"},
                "capabilities": {},
            },
        )
        pretty("Initialize", init_result)

        tools = client.request("tools/list", {})
        pretty("Tools", tools)

        added = client.request(
            "tools/call",
            {"name": "add_todo", "arguments": {"task": "Learn MCP basics"}},
        )
        pretty("Added Todo", added)

        listed = client.request("tools/call", {"name": "list_todos", "arguments": {}})
        pretty("All Todos", listed)
    finally:
        client.close()


if __name__ == "__main__":
    run_learning_agent()
