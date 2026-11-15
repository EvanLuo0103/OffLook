from pathlib import Path
import tempfile
import unittest

from offlook.core import (
    AiError,
    AiMessageResult,
    AiProvider,
    OpenAiCompatibleProvider,
    ToolCall,
    default_tools,
    run_instruction,
)


class ScriptedProvider(AiProvider):
    """Return a fixed sequence of assistant turns for deterministic tests."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = 0

    def complete(self, messages, tools=()):
        self.calls += 1
        return self.turns.pop(0)


class AiTests(unittest.TestCase):
    def test_default_tool_definitions(self):
        names = [definition["function"]["name"] for definition in default_tools().definitions()]
        self.assertEqual(
            names,
            ["list_files", "filter_files", "move_files", "copy_files", "organize_by_kind"],
        )

    def test_filter_tool_executes_locally(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.pdf").write_bytes(b"%PDF-1.4")
            tools = default_tools()
            outcome = tools.execute("filter_files", {"folder": str(root), "kinds": ["pdf"]})
            self.assertEqual([item["name"] for item in outcome], ["a.pdf"])

    def test_run_instruction_executes_tool_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "x.pdf").write_bytes(b"%PDF-1.4")
            tools = default_tools()
            provider = ScriptedProvider([
                AiMessageResult("", (ToolCall("c1", "filter_files", {"folder": str(root), "kinds": ["pdf"]}),), "tool_calls"),
                AiMessageResult("Found one PDF.", (), "stop"),
            ])
            result = run_instruction("find pdfs", provider=provider, tools=tools)
            self.assertEqual(result.answer, "Found one PDF.")
            self.assertEqual([step.name for step in result.steps], ["filter_files"])
            self.assertEqual(result.steps[0].result[0]["name"], "x.pdf")

    def test_run_instruction_stops_at_step_limit(self):
        tools = default_tools()
        provider = ScriptedProvider([
            AiMessageResult("", (ToolCall(f"c{i}", "list_files", {"folder": str(Path(tempfile.gettempdir()))}),), "tool_calls")
            for i in range(10)
        ])
        result = run_instruction("list", provider=provider, tools=tools, max_steps=3)
        self.assertEqual(len(result.steps), 3)
        self.assertIn("step limit", result.answer)

    def test_provider_requires_api_key(self):
        provider = OpenAiCompatibleProvider("https://api.deepseek.com", "", "deepseek-chat")
        with self.assertRaises(AiError):
            provider.complete([{"role": "user", "content": "hi"}])


if __name__ == "__main__":
    unittest.main()
