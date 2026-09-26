"""OpenCode CLI client for daily-report analysis sessions.

Drops in as a near-replacement for ``claude_agent_sdk.ClaudeSDKClient``:
same ``async with`` / ``receive_messages()`` shape so ``core.interactive.py``
can be migrated by replacing the SDK call site only.

OpenCode's ``run --format json`` emits JSONL on stdout with three top-level
event shapes:

    {"type":"step_start",  "sessionID":"...", "part":{"type":"step-start", ...}}
    {"type":"text",        "sessionID":"...", "part":{"type":"text", "text":"..."}}
    {"type":"tool_use",    "sessionID":"...", "part":{"type":"tool", "tool":"bash",
        "callID":"...", "state":{"status":"completed","input":{...},
        "output":"...","metadata":{"exit":0,...}}}}
    {"type":"step_finish", "sessionID":"...", "part":{"type":"step-finish",
        "reason":"tool-calls"|"stop", ...}}

We normalise them into ``AssistantMessage`` / ``StreamEvent`` /
``ResultMessage`` instances that mirror ``claude_agent_sdk`` types, so
``interactive.py`` can keep its existing event-handler code.
"""

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, List, Optional


DEFAULT_OPENCODE_PATH = Path.home() / ".opencode" / "bin" / "opencode"


def resolve_opencode_path(explicit: Optional[str] = None) -> str:
    """Locate the opencode CLI binary.

    Order: explicit arg > ``$OPENCODE_BIN`` > ``~/.opencode/bin/opencode`` >
    ``which opencode`` (PATH lookup).
    """
    if explicit:
        return explicit
    env = os.environ.get("OPENCODE_BIN")
    if env:
        return env
    if DEFAULT_OPENCODE_PATH.exists():
        return str(DEFAULT_OPENCODE_PATH)
    on_path = shutil.which("opencode")
    if on_path:
        return on_path
    raise FileNotFoundError(
        "opencode CLI not found. Set OPENCODE_BIN or install opencode."
    )


@dataclass
class OpencodeOptions:
    """Settings for one analysis session."""

    model: str  # e.g. "opencode-go/minimax-m3" or "anthropic/claude-sonnet-4-6"
    cwd: str  # directory the agent works in (e.g. backend/reports/002142)
    auto_approve: bool = True  # maps to --auto
    opencode_path: Optional[str] = None  # override binary location
    extra_args: List[str] = field(default_factory=list)  # pass-through flags
    env: dict = field(default_factory=dict)  # extra env vars


@dataclass
class TextBlock:
    text: str


@dataclass
class AssistantMessage:
    content: List[TextBlock]

    @property
    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))


@dataclass
class StreamEvent:
    """Mirrors ``claude_agent_sdk.types.StreamEvent``.

    The ``event`` dict shape mirrors Claude's stream events so the existing
    handler in ``interactive._handle_stream_event`` can keep working.
    """

    event: dict


@dataclass
class ResultMessage:
    is_error: bool
    result: str = ""
    session_id: str = ""
    cost: float = 0.0
    reason: str = ""  # "stop" | "tool-calls" | "error" | ...


class OpencodeClient:
    """Async context manager wrapping ``opencode run --format json``."""

    def __init__(self, options: OpencodeOptions):
        self.options = options
        self._process: Optional[asyncio.subprocess.Process] = None
        self._prompt: str = ""
        self._session_id: str = ""

    async def __aenter__(self) -> "OpencodeClient":
        binary = resolve_opencode_path(self.options.opencode_path)
        cmd = [
            binary,
            "run",
            "--model", self.options.model,
            "--dir", self.options.cwd,
            "--format", "json",
        ]
        if self.options.auto_approve:
            cmd.append("--auto")
        if "--print-logs" in self.options.extra_args:
            cmd.append("--print-logs")
        # append extra args before positional message
        cmd.extend(self.options.extra_args)

        env = os.environ.copy()
        env.update(self.options.env)

        # Pass the prompt as a single positional argument. opencode accepts
        # `opencode run [message..]` and joins them.
        cmd.append(self._prompt)

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.options.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        proc = self._process
        if proc is None:
            return False
        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
        return False

    def run(self, prompt: str) -> None:
        """Set the prompt. Must be called before ``__aenter__``."""
        self._prompt = prompt

    @property
    def session_id(self) -> str:
        return self._session_id

    async def receive_messages(self) -> AsyncIterator:
        """Yield normalised messages parsed from the JSONL stdout stream.

        Always yields a final ``ResultMessage`` once the process exits.
        """
        proc = self._process
        if proc is None or proc.stdout is None:
            yield ResultMessage(is_error=True, result="client not started")
            return

        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            self._session_id = event.get("sessionID", self._session_id) or self._session_id

            ev_type = event.get("type", "")
            part = event.get("part", {}) or {}
            part_type = part.get("type", "")

            if ev_type == "text" or part_type == "text":
                text = part.get("text", "")
                if text:
                    yield AssistantMessage(content=[TextBlock(text=text)])
            elif ev_type == "tool_use" or part_type == "tool":
                stream_event = self._convert_tool_use(event, part)
                if stream_event is not None:
                    yield stream_event
            elif ev_type == "step_finish" or part_type == "step-finish":
                # We yield the ResultMessage once at process exit so the
                # consumer has a stable "done" signal even if opencode emits
                # multiple step_finish events in one run.
                continue
            # ignore step_start and other lifecycle events

        rc = await proc.wait()
        stderr_tail = ""
        if proc.stderr is not None:
            try:
                stderr_bytes = await asyncio.wait_for(proc.stderr.read(), timeout=0.5)
                stderr_tail = stderr_bytes.decode("utf-8", errors="replace")[-400:]
            except asyncio.TimeoutError:
                stderr_tail = ""

        is_error = rc != 0
        yield ResultMessage(
            is_error=is_error,
            result=stderr_tail if is_error else "",
            session_id=self._session_id,
            cost=0.0,
            reason="error" if is_error else "stop",
        )

    def _convert_tool_use(self, event: dict, part: dict) -> Optional[StreamEvent]:
        tool = part.get("tool", "")
        state = part.get("state", {}) or {}
        tool_input = state.get("input", {}) or {}
        output = state.get("output", "") or ""
        meta = state.get("metadata", {}) or {}
        status = state.get("status", "unknown")
        exit_code = meta.get("exit")

        # CRITICAL: do NOT pass through state.output or metadata.output
        # verbatim — a single 60-bar K-line command produces ~20 KB of JSON
        # which blows past h11's 16 KB chunk limit when SSE-encodes this
        # event. The downstream consumer (interactive._handle_stream_event)
        # only reads ``name`` + ``partial[:300]`` anyway.
        input_summary = json.dumps(tool_input, ensure_ascii=False)[:200]
        output_preview = output[:200].replace("\n", " ⏎ ")
        message = f"{tool}({input_summary}) → {output_preview}" if output else f"{tool}({input_summary})"

        stream_evt = {
            "type": "task_progress",
            "data": {
                "task_type": tool,
                "status": status,
                "message": message,
                "exit": exit_code,
            },
            "name": tool,
            "partial": output[:300] if output else input_summary,
        }
        return StreamEvent(event=stream_evt)

    async def cancel(self) -> None:
        """Terminate the underlying process without waiting for clean exit."""
        proc = self._process
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            proc.kill()
