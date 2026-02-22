#!/usr/bin/env python3
"""LLM-orchestrated MCP learning agent.

This script accepts a plain-text user query, asks an LLM whether to call MCP tools,
executes selected tools, and then asks the LLM to produce a final natural-language answer.

Requirements:
- OPENAI_API_KEY in environment for real LLM mode.
- If no key is present, it falls back to a tiny heuristic planner for learning/demo use.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
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


def parse_tool_content(result: dict[str, Any]) -> Any:
    items = result.get("content", [])
    if not items:
        return result
    text = items[0].get("text", "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _post_openai_chat(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail}") from exc


def llm_plan_or_respond(query: str, tools: list[dict[str, Any]], api_key: str, model: str) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a learning assistant. Decide if MCP tools are needed. "
                "If needed, call exactly one tool."
            ),
        },
        {"role": "user", "content": query},
    ]

    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0,
    }
    response = _post_openai_chat(payload, api_key)
    msg = response["choices"][0]["message"]
    return msg


def llm_finalize_answer(
    query: str,
    tool_name: str,
    tool_result: Any,
    api_key: str,
    model: str,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Answer clearly for a beginner learning MCP.",
            },
            {
                "role": "user",
                "content": (
                    f"User query: {query}\n"
                    f"Tool called: {tool_name}\n"
                    f"Tool result JSON: {json.dumps(tool_result)}\n"
                    "Provide a concise helpful answer."
                ),
            },
        ],
        "temperature": 0.2,
    }
    response = _post_openai_chat(payload, api_key)
    return response["choices"][0]["message"]["content"]


def heuristic_plan(query: str) -> dict[str, Any]:
    lower = query.lower()
    if "add" in lower or "create" in lower:
        return {"tool": "add_todo", "arguments": {"task": query}}
    if "list" in lower or "show" in lower:
        return {"tool": "list_todos", "arguments": {}}
    return {"tool": "list_todos", "arguments": {}}


def run(query: str, model: str) -> None:
    client = MCPClient([sys.executable, str(SERVER_PATH)])
    try:
        client.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "llm-learning-agent", "version": "0.2.0"},
                "capabilities": {},
            },
        )

        available = client.request("tools/list", {}).get("tools", [])
        openai_tools = []
        for tool in available:
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                    },
                }
            )

        api_key = os.getenv("OPENAI_API_KEY", "")

        if api_key:
            planner_msg = llm_plan_or_respond(query, openai_tools, api_key, model)
            tool_calls = planner_msg.get("tool_calls", [])

            if tool_calls:
                call = tool_calls[0]
                fn = call["function"]["name"]
                raw_args = call["function"].get("arguments", "{}")
                args = json.loads(raw_args) if raw_args else {}
                result = client.request("tools/call", {"name": fn, "arguments": args})
                structured = parse_tool_content(result)
                final = llm_finalize_answer(query, fn, structured, api_key, model)
                print("Plan: used LLM + MCP tool")
                print(f"Tool: {fn}")
                print("Tool result:")
                print(json.dumps(structured, indent=2))
                print("\nFinal answer:")
                print(final)
            else:
                print("Plan: LLM answered directly (no tool needed)")
                print(planner_msg.get("content", ""))
        else:
            plan = heuristic_plan(query)
            result = client.request(
                "tools/call", {"name": plan["tool"], "arguments": plan["arguments"]}
            )
            structured = parse_tool_content(result)
            print("Plan: heuristic fallback (OPENAI_API_KEY not set)")
            print(f"Tool: {plan['tool']}")
            print(json.dumps(structured, indent=2))
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM-orchestrated MCP learning agent")
    parser.add_argument("query", nargs="?", default="Add a todo: Learn SQL joins")
    parser.add_argument("--model", default="gpt-4o-mini")
    args = parser.parse_args()
    run(args.query, args.model)


if __name__ == "__main__":
    main()
