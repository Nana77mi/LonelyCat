"""极简 MCP stdio 测试 server：一行一个 JSON，request_id，仅支持 tools/list、tools/call（Phase 2.2 v0.1）。"""

from __future__ import annotations

import json
import sys
import time

# 固定 tools 列表，供 tools/list
DEFAULT_TOOLS = [
    {"name": "ping", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "echo", "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}}},
]


def main() -> None:
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}
        if method == "tools/list":
            result = {"tools": DEFAULT_TOOLS}
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
            sys.stdout.flush()
        elif method == "tools/call":
            args = params.get("arguments") or {}
            delay = args.get("delay_sec")
            if isinstance(delay, (int, float)) and delay > 0:
                time.sleep(delay)
            result = {"content": [{"type": "text", "text": "ok"}]}
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
            sys.stdout.flush()
        else:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
