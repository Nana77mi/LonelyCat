"""MCPStdioClient: 手写最小 JSON-RPC over stdio，一行一 JSON + request_id（Phase 2.2 v0.1）."""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from worker.tools.mcp_errors import MCPConnectionError, MCPSpawnFailedError, MCPTimeoutError

logger = logging.getLogger(__name__)

MCP_SPAWN_FAILED = "mcp.spawn.failed"
CLOSE_TERMINATE_WAIT_SEC = 2.0
CLOSE_KILL_WAIT_SEC = 1.0


class MCPStdioClient:
    """同步外观：list_tools(timeout_ms)、call_tool(name, args, timeout_ms)、close()。内部后台线程读 stdout，按 id resolve。"""

    def __init__(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        self._cmd = list(cmd)
        self._cwd = cwd
        self._env = env
        self._process: Optional[subprocess.Popen] = None
        self._closed = False
        self._request_id = 0
        self._lock = threading.Lock()
        self._pending: Dict[int, queue.Queue] = {}  # id -> Queue of single result/exception
        self._reader_thread: Optional[threading.Thread] = None
        self._reader_stop = threading.Event()

    def _next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _ensure_process(self) -> None:
        if self._closed:
            raise MCPConnectionError("client closed")
        if self._process is not None:
            if self._process.poll() is not None:
                raise MCPConnectionError("process exited")
            return
        try:
            env = os.environ.copy()
            if self._env:
                env.update(self._env)
            self._process = subprocess.Popen(
                self._cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self._cwd,
                env=env,
                text=True,
                bufsize=1,
            )
        except OSError as e:
            logger.warning("%s cmd=%s error=%s", MCP_SPAWN_FAILED, self._cmd, e)
            raise MCPSpawnFailedError(str(e)) from e
        self._reader_stop.clear()
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=False)
        self._reader_thread.start()

    def _read_loop(self) -> None:
        try:
            while not self._reader_stop.is_set() and self._process and self._process.stdout:
                line = self._process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                req_id = msg.get("id")
                if req_id is None:
                    continue
                with self._lock:
                    q = self._pending.pop(req_id, None)
                if q is None:
                    continue
                if "error" in msg:
                    q.put(MCPConnectionError(msg["error"].get("message", "unknown")))
                else:
                    q.put(msg.get("result"))
        except Exception:
            pass
        finally:
            with self._lock:
                for q in self._pending.values():
                    try:
                        q.put(MCPConnectionError("connection closed"))
                    except Exception:
                        pass
                self._pending.clear()

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout_ms: int = 30_000) -> Any:
        self._ensure_process()
        req_id = self._next_id()
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._pending[req_id] = q
        req = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        try:
            if self._process and self._process.stdin:
                self._process.stdin.write(json.dumps(req) + "\n")
                self._process.stdin.flush()
        except Exception as e:
            with self._lock:
                self._pending.pop(req_id, None)
            raise MCPConnectionError(str(e)) from e
        timeout_sec = timeout_ms / 1000.0 if timeout_ms > 0 else 30.0
        try:
            result = q.get(timeout=timeout_sec)
        except queue.Empty:
            with self._lock:
                self._pending.pop(req_id, None)
            raise MCPTimeoutError("request timeout") from None
        if isinstance(result, Exception):
            raise result
        return result

    def list_tools(self, timeout_ms: int = 30_000) -> List[Dict[str, Any]]:
        """返回 tools 列表；失败抛 MCPSpawnFailedError / MCPTimeoutError / MCPConnectionError。"""
        result = self._request("tools/list", {}, timeout_ms=timeout_ms)
        if not isinstance(result, dict):
            return []
        tools = result.get("tools")
        if not isinstance(tools, list):
            return []
        return [t for t in tools if isinstance(t, dict) and t.get("name")]

    def call_tool(self, name: str, args: Dict[str, Any], timeout_ms: int = 30_000) -> Dict[str, Any]:
        """调用工具，返回 result dict；失败抛 MCPSpawnFailedError / MCPTimeoutError / MCPConnectionError。"""
        result = self._request("tools/call", {"name": name, "arguments": args}, timeout_ms=timeout_ms)
        if isinstance(result, dict):
            return result
        return {"result": result}

    def close(self) -> None:
        """先停 reader，再 terminate → 等待 → kill；幂等。"""
        if self._closed:
            return
        self._closed = True
        self._reader_stop.set()
        if self._process:
            try:
                if self._process.stdin:
                    self._process.stdin.close()
            except Exception:
                pass
            try:
                self._process.terminate()
                self._process.wait(timeout=CLOSE_TERMINATE_WAIT_SEC)
            except subprocess.TimeoutExpired:
                self._process.kill()
                try:
                    self._process.wait(timeout=CLOSE_KILL_WAIT_SEC)
                except subprocess.TimeoutExpired:
                    pass
            except Exception:
                pass
            self._process = None
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
