"""
In-process tools that wrap existing APIs. Each tool implements InProcessTool (name, description, parameters_schema, run).
"""

import logging
from typing import Any

from apis import facts as facts_api
from apis import joke as joke_api
from apis import nasa_apod as nasa_apod_api
from apis import pixabay as pixabay_api
from apis import stories as stories_api
from apis import trivia as trivia_api
import llm

from .context import RoutingContext
from .protocol import InProcessTool, ollama_tool_definition
from .result import ToolResult

logger = logging.getLogger(__name__)


class JokeTool:
    name = "get_joke"
    description = "Get a random kid-friendly joke. Use when the child wants a joke or something funny."
    parameters_schema = None

    async def run(self, ctx: RoutingContext, arguments: dict[str, Any]) -> ToolResult:
        joke = await joke_api.fetch_joke()
        if joke:
            setup, punchline = joke
            text = joke_api.format_joke_for_reply(setup, punchline)
            return ToolResult(text=text)
        return ToolResult(text="I couldn't fetch a joke right now. Want to try again?")


class StoryTool:
    name = "get_story"
    description = "Get a short story or bedtime tale for the child. Use when they ask for a story or tale."
    parameters_schema = None

    async def run(self, ctx: RoutingContext, arguments: dict[str, Any]) -> ToolResult:
        story_data = await stories_api.fetch_random_story()
        if story_data:
            text = stories_api.format_story_for_reply(
                story_data["title"], story_data["author"],
                story_data["story"], story_data["moral"],
            )
            return ToolResult(text=text)
        fact = await facts_api.fetch_random_fact()
        if fact:
            return ToolResult(text=f"Story seed: {fact}")
        return ToolResult(text="I couldn't fetch a story right now. Want to try again?")


class FactTool:
    name = "get_fact"
    description = "Get a random interesting fact for the child. Use when they ask for a fact or something interesting."
    parameters_schema = None

    async def run(self, ctx: RoutingContext, arguments: dict[str, Any]) -> ToolResult:
        fact = await facts_api.fetch_random_fact()
        if fact:
            return ToolResult(text=fact)
        return ToolResult(text="I couldn't fetch a fact right now. Want to try again?")


class SpaceTool:
    name = "get_space_picture"
    description = (
        "Get the astronomy picture of the day (NASA APOD) or a random past space picture. "
        "Use when the child wants a space or astronomy picture, or says 'one more picture' after a space reply."
    )
    parameters_schema = None

    async def run(self, ctx: RoutingContext, arguments: dict[str, Any]) -> ToolResult:
        use_random_date = bool(
            ctx.last_assistant_message
            and nasa_apod_api.last_message_suggests_space(ctx.last_assistant_message)
            and nasa_apod_api.user_asking_for_another_picture(ctx.user_message)
        )
        apod = await nasa_apod_api.fetch_apod(use_random_date=use_random_date)
        if not apod:
            return ToolResult(text="I couldn't fetch the space picture right now. Want to try again?")
        img_bytes, media_type, title, explanation = apod
        first_sentence = (explanation.split(".")[0].strip() + ".") if explanation else ""
        if use_random_date:
            text = f"Here's another space picture! {title}. {first_sentence}" if first_sentence else f"Here's another space picture! {title}"
        else:
            text = f"Here's today's space picture! {title}. {first_sentence}" if first_sentence else f"Here's today's space picture! {title}"
        return ToolResult(text=text, image=(img_bytes, media_type))


class SearchImageTool:
    name = "search_image"
    description = (
        "Search for a picture by keywords (e.g. dog, castle, sunset). "
        "Use when the child wants a picture of something that is not space/astronomy."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "string",
                "description": "2-5 English keywords for the image search (e.g. 'dog', 'sunset castle').",
            },
        },
    }

    async def run(self, ctx: RoutingContext, arguments: dict[str, Any]) -> ToolResult:
        keywords = (arguments.get("keywords") or "").strip() if isinstance(arguments, dict) else ""
        if not keywords:
            keywords = llm.image_search_keywords_heuristic(ctx.user_message)
        if not keywords:
            keywords = await llm.extract_image_search_keywords(ctx.user_message)
        result = await pixabay_api.fetch_image(keywords)
        if result:
            img_bytes, media_type = result
            return ToolResult(text="Here's a picture for you!", image=(img_bytes, media_type))
        return ToolResult(text="I couldn't find a picture for that right now. Want to try different words?")


class QuizTool:
    name = "get_quiz"
    description = "Get a kid-friendly trivia or quiz question (multiple choice). Use when the child wants a quiz or question."
    parameters_schema = None

    async def run(self, ctx: RoutingContext, arguments: dict[str, Any]) -> ToolResult:
        quiz_data = await trivia_api.fetch_quiz_question()
        if quiz_data:
            text = trivia_api.format_quiz_for_reply(quiz_data)
            return ToolResult(text=text)
        return ToolResult(text="I couldn't fetch a quiz question right now. Want to try again?")


def _safe_eval_expression(expr: str):
    """
    Evaluate a simple math expression containing only 0-9, ., +, -, *, /, (, ), and spaces.
    Uses simpleeval if available; otherwise a minimal safe evaluator (no eval() of arbitrary code).
    """
    try:
        from simpleeval import SimpleEval
        return SimpleEval().eval(expr)
    except ImportError:
        pass
    # Fallback: only allow digits, decimal, and + - * / ( )
    allowed = set("0123456789.+-*/() ")
    if not all(c in allowed for c in expr):
        raise ValueError("Invalid characters")
    # Tokenize: numbers and operators
    tokens = []
    i = 0
    while i < len(expr):
        c = expr[i]
        if c in " ":
            i += 1
            continue
        if c in "+-*/()":
            tokens.append(c)
            i += 1
            continue
        if c.isdigit() or c == ".":
            start = i
            while i < len(expr) and (expr[i].isdigit() or expr[i] == "."):
                i += 1
            tokens.append(expr[start:i])
            continue
        raise ValueError("Invalid character")
    if not tokens:
        raise ValueError("Empty expression")

    def parse_primary(idx):
        if idx >= len(tokens):
            raise ValueError("Unexpected end")
        t = tokens[idx]
        if t == "(":
            val, idx = parse_add(idx + 1)
            if idx >= len(tokens) or tokens[idx] != ")":
                raise ValueError("Missing )")
            return val, idx + 1
        if t in "+-":
            val, idx = parse_primary(idx + 1)
            return -val if t == "-" else val, idx
        try:
            return float(t) if "." in t else int(t), idx + 1
        except ValueError:
            raise ValueError("Invalid number")

    def parse_mul(idx):
        val, idx = parse_primary(idx)
        while idx < len(tokens) and tokens[idx] in "*/":
            op = tokens[idx]
            right, idx = parse_primary(idx + 1)
            if op == "*":
                val *= right
            else:
                if right == 0:
                    raise ValueError("Division by zero")
                val /= right
        return val, idx

    def parse_add(idx):
        val, idx = parse_mul(idx)
        while idx < len(tokens) and tokens[idx] in "+-":
            op = tokens[idx]
            right, idx = parse_mul(idx + 1)
            val = val + right if op == "+" else val - right
        return val, idx

    val, idx = parse_add(0)
    if idx != len(tokens):
        raise ValueError("Extra tokens")
    return val


class CalculatorTool:
    name = "calculate"
    description = (
        "Evaluate a math expression when the child asks for a calculation (e.g. what is 5+3, how much is 10 times 2). "
        "Pass the expression using only numbers and + - * / ( ). Do not compute math yourself."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Math expression to evaluate, e.g. '2+3', '10*5', '100/4'. Use only numbers and + - * / ( ).",
            },
        },
    }

    async def run(self, ctx: RoutingContext, arguments: dict[str, Any]) -> ToolResult:
        raw = (arguments.get("expression") or "").strip() if isinstance(arguments, dict) else ""
        if not raw or len(raw) > 200:
            return ToolResult(text="Give me a simple math problem like 2 + 3!")
        try:
            result = _safe_eval_expression(raw)
        except Exception:
            return ToolResult(text="That one's tricky. Try something like 4 + 5!")
        if isinstance(result, float):
            if result == int(result):
                result = int(result)
            else:
                result = round(result, 10)
        return ToolResult(text=str(result))


# Singleton instances for the registry
JOKE_TOOL = JokeTool()
STORY_TOOL = StoryTool()
FACT_TOOL = FactTool()
SPACE_TOOL = SpaceTool()
SEARCH_IMAGE_TOOL = SearchImageTool()
QUIZ_TOOL = QuizTool()
CALCULATOR_TOOL = CalculatorTool()

ALL_IN_PROCESS_TOOLS: list[InProcessTool] = [
    JOKE_TOOL,
    STORY_TOOL,
    FACT_TOOL,
    SPACE_TOOL,
    SEARCH_IMAGE_TOOL,
    QUIZ_TOOL,
    CALCULATOR_TOOL,
]
