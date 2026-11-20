"""Opt-in AI assistant port: a provider-neutral bridge to file-management tools.

OffLook stays offline by default. Enabling the assistant and supplying an API
key makes exactly one class of network call — a POST to the user's configured
OpenAI-compatible ``/chat/completions`` endpoint (DeepSeek, OpenAI, and many
self-hosted servers use this shape). No other telemetry is sent.

The assistant is a thin loop: the model receives the user's instruction plus
JSON tool definitions. The default tools are read-only unless the caller supplies
a callback to review exact local file changes before execution. Tool results are
returned to the model, and the final answer is shown to the user.
Providers are plain Python and can be subclassed for non-OpenAI APIs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from urllib.error import HTTPError

from .errors import AiError, FileAccessError
from .file_ops import AiWritePlan, execute_ai_write, list_folder, prepare_ai_write
from .files import FileKind
from .search import filter_files

_MAX_RESULTS = 200
_MAX_TOOL_RESULT_CHARS = 8000


@dataclass(frozen=True)
class ToolCall:
    """A single function call requested by the model."""

    id: str
    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class AiMessageResult:
    """The model's textual reply, optional tool calls, and finish reason."""

    content: str
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str


@dataclass(frozen=True)
class ToolStep:
    """A recorded tool execution for the user-facing transcript."""

    name: str
    arguments: Mapping[str, object]
    result: object
    error: str = ""


@dataclass(frozen=True)
class AiRunResult:
    """The final assistant answer and every tool step it requested."""

    answer: str
    steps: tuple[ToolStep, ...]


class AiProvider(ABC):
    """Provider interface: turn a message list into one assistant turn."""

    @abstractmethod
    def complete(
        self,
        messages: list[dict[str, object]],
        tools: tuple[dict[str, object], ...] = (),
    ) -> AiMessageResult:
        """Return the assistant turn for ``messages``; raise AiError on failure."""
        raise NotImplementedError


class OpenAiCompatibleProvider(AiProvider):
    """Call an OpenAI-compatible chat-completions endpoint using only the stdlib."""

    def __init__(self, base_url: str, api_key: str, model: str, *, timeout: float = 60.0) -> None:
        """Configure the endpoint; no network request is made here."""
        self.base_url = _clean_base_url(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(
        self,
        messages: list[dict[str, object]],
        tools: tuple[dict[str, object], ...] = (),
    ) -> AiMessageResult:
        if not self.api_key:
            raise AiError("An API key is required before using the AI assistant")
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"
        try:
            import urllib.request

            request = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            return _parse_completion(body)
        except HTTPError as exc:
            status = exc.code
            error = "AI request failed (HTTPError)."
            if type(status) is int:
                error = f"AI request failed (HTTP {status})."
        except Exception as exc:
            error = f"AI request failed ({type(exc).__name__})."
        # Do not chain exceptions that can contain URLs, request data, or credentials.
        raise AiError(error)


def _clean_base_url(base_url: str) -> str:
    """Normalize a base URL so the provider can append ``/chat/completions``."""
    if not isinstance(base_url, str) or not base_url.strip():
        raise AiError("The AI base URL must be a nonblank HTTP(S) URL")
    cleaned = base_url.strip().rstrip("/")
    if not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        raise AiError("The AI base URL must start with http:// or https://")
    return cleaned


def _parse_completion(body: object) -> AiMessageResult:
    """Extract content, tool calls, and finish reason from a completion body."""
    if not isinstance(body, dict):
        raise AiError("The AI provider returned an invalid response")
    try:
        choices = body["choices"]
        choice = choices[0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AiError("The AI provider response has no choices") from exc
    content = message.get("content") or ""
    if not isinstance(content, str):
        content = ""
    tool_calls: list[ToolCall] = []
    for raw in message.get("tool_calls") or []:
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") or {}
        name = function.get("name")
        arguments_raw = function.get("arguments") or "{}"
        if isinstance(arguments_raw, dict):
            arguments = arguments_raw
        else:
            try:
                arguments = json.loads(arguments_raw) if arguments_raw else {}
            except (TypeError, ValueError):
                arguments = {}
        if isinstance(name, str) and isinstance(arguments, dict):
            tool_calls.append(ToolCall(str(raw.get("id") or name), name, arguments))
    finish_reason = str(choice.get("finish_reason") or "stop")
    return AiMessageResult(content, tuple(tool_calls), finish_reason)


class AiToolRegistry:
    """Store named local tools with JSON schemas; dispatch by name.

    Tool callbacks receive one decoded ``dict`` of arguments and must return a
    JSON-serializable value. They are trusted local code and must enforce the
    offline and local-path rules themselves.
    """

    def __init__(self) -> None:
        self._tools: dict[str, tuple[str, dict[str, object], Callable[[dict[str, object]], object]]] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, object],
        callback: Callable[[dict[str, object]], object],
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise AiError("The tool name must be a nonempty string")
        if name in self._tools:
            raise AiError(f"Tool already registered: {name}")
        if not callable(callback):
            raise AiError("The tool callback must be callable")
        self._tools[name] = (description, dict(parameters), callback)

    def definitions(self) -> tuple[dict[str, object], ...]:
        """Return OpenAI-format function definitions for every registered tool."""
        result: list[dict[str, object]] = []
        for name, (description, parameters, _callback) in self._tools.items():
            result.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            })
        return tuple(result)

    def execute(self, name: str, arguments: Mapping[str, object]) -> object:
        """Run a tool by name, wrapping callback failures with their cause."""
        try:
            _description, _parameters, callback = self._tools[name]
        except KeyError as exc:
            raise AiError(f"Tool not registered: {name}") from exc
        try:
            return callback(dict(arguments))
        except AiError:
            raise
        except Exception as exc:
            raise AiError(f"Tool execution failed: {name} ({type(exc).__name__})") from exc


def _serialize_paths(paths: tuple[Path, ...]) -> list[dict[str, object]]:
    """Summarize files with bounded fields for a model tool result."""
    output: list[dict[str, object]] = []
    for path in paths:
        try:
            stat = path.stat()
            size = stat.st_size
        except OSError:
            size = 0
        output.append({
            "path": str(path),
            "name": path.name,
            "extension": path.suffix.lower(),
            "size_bytes": size,
        })
        if len(output) >= _MAX_RESULTS:
            break
    return output


def _kind_name(value: object) -> FileKind:
    """Map a model-supplied kind string to a FileKind, tolerating labels."""
    if not isinstance(value, str):
        raise AiError("A document type must be a string such as 'pdf' or 'image'")
    token = value.strip().lower()
    aliases = {
        "image": "image", "images": "image", "pdf": "pdf", "text": "text",
        "markdown": "markdown", "code": "code", "csv": "csv",
        "document": "document", "documents": "document", "binary": "binary",
        "other": "binary", "unknown": "binary",
    }
    token = aliases.get(token, token)
    try:
        return FileKind(token)
    except ValueError:
        raise AiError("Unsupported document type") from None


def default_tools(*, approve_write: Callable[[AiWritePlan], bool] | None = None) -> AiToolRegistry:
    """Build read-only tools, adding writes only with a local approval callback."""
    registry = AiToolRegistry()

    registry.register(
        "list_files",
        "List local files under a folder, optionally matching a filename fragment.",
        {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Absolute local folder path."},
                "filename": {"type": "string", "description": "Optional case-insensitive filename fragment."},
            },
            "required": ["folder"],
        },
        lambda args: _serialize_paths(list_folder(args["folder"], filename=str(args.get("filename") or ""))),
    )

    registry.register(
        "filter_files",
        "List files under a folder filtered by extension and/or document kind (pdf, image, text, code, csv, document, etc.).",
        {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Absolute local folder path."},
                "extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional extensions like ['.pdf', '.docx'].",
                },
                "kinds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional categories like ['pdf', 'image'].",
                },
                "filename": {"type": "string", "description": "Optional filename fragment."},
            },
            "required": ["folder"],
        },
        lambda args: _serialize_paths(tuple(
            result.path
            for result in filter_files(
                args["folder"],
                filename=str(args.get("filename") or ""),
                extensions=[str(item) for item in (args.get("extensions") or [])],
                kinds=[_kind_name(item) for item in (args.get("kinds") or [])],
            )
        )),
    )

    if approve_write is None:
        return registry
    if not callable(approve_write):
        raise AiError("File changes require a callable approval callback")

    def _write_tool(tool: str) -> Callable[[dict[str, object]], object]:
        def run(args: dict[str, object]) -> dict[str, object]:
            if tool == "organize_by_kind" and "kinds" in args:
                kinds = args["kinds"]
                if not isinstance(kinds, list) or not all(isinstance(kind, str) for kind in kinds):
                    raise AiError("Document kinds must be a list of strings")
                args["kinds"] = [_kind_name(kind).value for kind in kinds]
            try:
                plan = prepare_ai_write(tool, args)
            except FileAccessError as exc:
                raise AiError(str(exc)) from None
            if any(not item.skip for item in plan.items) and approve_write(plan) is not True:
                raise AiError("File changes were not approved; nothing was changed.")
            try:
                results = execute_ai_write(plan)
            except FileAccessError as exc:
                raise AiError(str(exc)) from None
            return {
                "results": [
                    {"source": str(item.source), "destination": str(item.destination),
                     "status": item.status, "message": item.message}
                    for item in results
                ]
            }
        return run

    conflict_parameter = {"type": "string", "enum": ["rename", "skip"], "default": "rename"}
    for tool, action in (("move_files", "move"), ("copy_files", "copy")):
        registry.register(
            tool,
            f"Request approval to {action} local files into an existing destination folder.",
            {
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "Absolute source file paths."},
                    "destination": {"type": "string", "description": "Absolute destination folder."},
                    "conflict": conflict_parameter,
                },
                "required": ["paths", "destination"],
            },
            _write_tool(tool),
        )

    registry.register(
        "organize_by_kind",
        "Request approval to move local files into per-type subfolders under an existing destination folder.",
        {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Absolute local source folder path."},
                "destination": {"type": "string", "description": "Absolute destination root folder."},
                "kinds": {"type": "array", "items": {"type": "string"}, "description": "Categories like ['pdf', 'image']."},
                "conflict": conflict_parameter,
            },
            "required": ["folder", "destination"],
        },
        _write_tool("organize_by_kind"),
    )

    return registry


_SYSTEM_PROMPT = (
    "You are OffLook's file-management assistant running on the user's Windows PC. "
    "Help the user find, filter, organize, and archive their local files. "
    "Use the provided tools to act on real files; never invent file or folder paths. "
    "Only operate on local drive-letter paths the user provided or that a tool returned. "
    "File changes require local approval. A denied change did not happen; do not retry it automatically. "
    "Describe what actually happened according to the tool results. "
    "If an operation fails, report the failure instead of retrying blindly. "
    "Keep answers concise and in the language the user wrote."
)


def _bounded_tool_result(value: object) -> str:
    """Serialize a tool result for the model within a character budget."""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > _MAX_TOOL_RESULT_CHARS:
        text = text[: _MAX_TOOL_RESULT_CHARS] + "…(truncated)"
    return text


def run_instruction(
    instruction: str,
    *,
    provider: AiProvider,
    tools: AiToolRegistry | None = None,
    max_steps: int = 8,
) -> AiRunResult:
    """Run one user instruction through the tool-calling loop and return the answer.

    ``provider`` performs the network calls; ``tools`` supplies the local
    operations the model may request. The loop runs synchronously on the
    caller's thread, so the GUI must invoke this from a worker.
    """
    if not isinstance(instruction, str) or not instruction.strip():
        raise AiError("Enter an instruction for the assistant")
    registry = tools if tools is not None else default_tools()
    definitions = registry.definitions()
    messages: list[dict[str, object]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]
    steps: list[ToolStep] = []
    for _index in range(max_steps):
        result = provider.complete(messages, definitions)
        if not result.tool_calls or result.finish_reason != "tool_calls":
            return AiRunResult(result.content.strip(), tuple(steps))
        assistant_message: dict[str, object] = {
            "role": "assistant",
            "content": result.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
                }
                for call in result.tool_calls
            ],
        }
        messages.append(assistant_message)
        for call in result.tool_calls:
            try:
                outcome = registry.execute(call.name, call.arguments)
                error = ""
                result_text = _bounded_tool_result(outcome)
            except AiError as exc:
                outcome = None
                error = str(exc)
                result_text = error
            steps.append(ToolStep(call.name, call.arguments, outcome, error))
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result_text,
            })
    return AiRunResult("The assistant did not finish within the step limit.", tuple(steps))


__all__ = [
    "AiError",
    "AiMessageResult",
    "AiProvider",
    "AiRunResult",
    "AiToolRegistry",
    "OpenAiCompatibleProvider",
    "ToolCall",
    "ToolStep",
    "default_tools",
    "run_instruction",
]
