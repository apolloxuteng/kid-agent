"""
In-process tools that wrap existing APIs. Each tool implements InProcessTool (name, description, parameters_schema, run).
"""

import asyncio
import json
import logging
import random
import re
from typing import Any

from apis import joke as joke_api
import db
import llm

from .context import RoutingContext
from .protocol import InProcessTool, ollama_tool_definition
from .result import ToolResult

logger = logging.getLogger(__name__)


WORD_OF_DAY_REQUEST_PHRASES = (
    "word of the day",
    "new word",
    "teach me a word",
    "learn a word",
    "vocabulary word",
    "today's word",
    "todays word",
)

WORD_REVIEW_REQUEST_PHRASES = (
    "what words did i learn",
    "what words have i learned",
    "words i learned",
    "learned words",
    "review my words",
    "show my words",
    "show me my words",
    "what are my words",
    "which words did i learn",
    "which words have i learned",
)

DEFINE_WORD_PATTERNS = (
    r"what does ['\"]?([a-zA-Z][a-zA-Z\-']{1,30})['\"]? mean\??$",
    r"what is the meaning of ['\"]?([a-zA-Z][a-zA-Z\-']{1,30})['\"]?\??$",
    r"what's the meaning of ['\"]?([a-zA-Z][a-zA-Z\-']{1,30})['\"]?\??$",
    r"define ['\"]?([a-zA-Z][a-zA-Z\-']{1,30})['\"]?\??$",
)

WORD_BANK: tuple[tuple[str, str, str], ...] = (
    ("curious", "wanting to learn or know more about something", "Mia was curious about how butterflies fly."),
    ("brave", "doing something even when it feels a little scary", "Leo was brave when he tried the tall slide."),
    ("gentle", "soft and careful, not rough", "Use a gentle touch when you pet a small puppy."),
    ("discover", "to find or learn something new", "We can discover tiny shells at the beach."),
    ("patient", "able to wait calmly", "Nora was patient while the cookies baked."),
    ("sparkle", "to shine with little flashes of light", "The snow can sparkle in the morning sun."),
    ("cozy", "warm, comfortable, and safe-feeling", "A blanket can feel cozy on a rainy day."),
    ("imagine", "to make a picture or idea in your mind", "You can imagine a castle in the clouds."),
    ("tiny", "very small", "An ant is tiny compared with your shoe."),
    ("enormous", "very, very big", "A whale is an enormous animal."),
    ("whisper", "to speak very softly", "We whisper in the library so others can read."),
    ("gather", "to bring things together", "Let's gather the blocks before dinner."),
    ("clever", "good at thinking of smart ideas", "The clever fox found a way around the fence."),
    ("protect", "to keep someone or something safe", "A helmet helps protect your head."),
    ("delight", "a happy feeling", "Finding a surprise note can bring delight."),
    ("wiggle", "to move with small quick motions", "The puppy's tail began to wiggle."),
    ("peaceful", "calm and quiet", "The garden felt peaceful after the rain."),
    ("create", "to make something new", "You can create a picture with crayons."),
    ("observe", "to look carefully and notice things", "Scientists observe bugs with a magnifying glass."),
    ("kindness", "being friendly and caring", "Sharing your toy is an act of kindness."),
)


def user_asking_for_word_of_day(message: str) -> bool:
    """Return True if the message is asking to learn a vocabulary word."""
    if not message or not message.strip():
        return False
    lower = message.strip().lower()
    return any(phrase in lower for phrase in WORD_OF_DAY_REQUEST_PHRASES)


def user_asking_to_review_words(message: str) -> bool:
    """Return True if the message is asking to review previously taught words."""
    if not message or not message.strip():
        return False
    lower = message.strip().lower()
    return any(phrase in lower for phrase in WORD_REVIEW_REQUEST_PHRASES)


def extract_definition_word(message: str) -> str | None:
    """Extract the target word from clear definition requests."""
    if not message or not message.strip():
        return None
    text = message.strip().lower()
    for pattern in DEFINE_WORD_PATTERNS:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            word = match.group(1).strip(" '\"").lower()
            if 2 <= len(word) <= 30:
                return word
    return None


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


class WordOfDayTool:
    name = "get_word_of_day"
    description = "Teach one kid-friendly English vocabulary word, with a simple meaning and example."
    parameters_schema = None

    async def run(self, ctx: RoutingContext, arguments: dict[str, Any]) -> ToolResult:
        word, meaning, example = random.choice(WORD_BANK)
        saved = await asyncio.to_thread(db.save_learned_word, ctx.profile_id, word, meaning, example)
        if not saved:
            logger.warning("Failed to store word of the day for profile_id=%s", ctx.profile_id)
        text = f"Today's word is {word}. It means {meaning}. Example: {example}"
        return ToolResult(text=text)


class ReviewWordsTool:
    name = "review_learned_words"
    description = "Review vocabulary words that have already been taught to this child."
    parameters_schema = None

    async def run(self, ctx: RoutingContext, arguments: dict[str, Any]) -> ToolResult:
        words = await asyncio.to_thread(db.load_learned_words, ctx.profile_id, 10)
        if not words:
            return ToolResult(text="We haven't learned any words yet. Tap Learn and I'll teach you one!")
        names = [w["word"] for w in words if w.get("word")]
        if len(names) == 1:
            text = f"You have learned this word so far: {names[0]}."
        else:
            text = "You have learned these words so far: " + ", ".join(names) + "."
        return ToolResult(text=text)


class DefineWordTool:
    name = "define_word"
    description = "Explain the meaning of a specific English word and store it for review."
    parameters_schema = {
        "type": "object",
        "properties": {
            "word": {
                "type": "string",
                "description": "The English word to define.",
            },
        },
    }

    async def run(self, ctx: RoutingContext, arguments: dict[str, Any]) -> ToolResult:
        raw_word = (arguments.get("word") or "").strip().lower() if isinstance(arguments, dict) else ""
        word = raw_word or extract_definition_word(ctx.user_message or "") or ""
        word = re.sub(r"[^a-zA-Z\-']", "", word).lower()
        if not word or len(word) > 30:
            return ToolResult(text="Tell me one word, like: What does curious mean?")

        fallback_meaning = f"the meaning of the word {word}"
        fallback_example = f"I learned the word {word} today."
        prompt = (
            "Explain one English vocabulary word for a curious 7-year-old. "
            "Return only JSON with keys word, meaning, example. "
            "The meaning should be one clear sentence. The example should be one natural sentence using the word. "
            f"Word: {word}"
        )
        data = await llm.call_ollama(prompt, timeout=20, raise_on_error=False)
        meaning = fallback_meaning
        example = fallback_example
        if data:
            try:
                parsed = json.loads(data)
                parsed_word = str(parsed.get("word") or word).strip().lower()
                if parsed_word:
                    word = re.sub(r"[^a-zA-Z\-']", "", parsed_word).lower() or word
                parsed_meaning = str(parsed.get("meaning") or "").strip()
                parsed_example = str(parsed.get("example") or "").strip()
                if parsed_meaning:
                    meaning = parsed_meaning
                if parsed_example:
                    example = parsed_example
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.warning("Definition JSON parse failed for word=%s response=%r", word, data[:200])

        saved = await asyncio.to_thread(db.save_learned_word, ctx.profile_id, word, meaning, example)
        if not saved:
            logger.warning("Failed to store defined word for profile_id=%s word=%s", ctx.profile_id, word)
        return ToolResult(text=f"{word.capitalize()} means {meaning} Example: {example}")


# Singleton instances for the registry
JOKE_TOOL = JokeTool()
CALCULATOR_TOOL = CalculatorTool()
WORD_OF_DAY_TOOL = WordOfDayTool()
REVIEW_WORDS_TOOL = ReviewWordsTool()
DEFINE_WORD_TOOL = DefineWordTool()

ALL_IN_PROCESS_TOOLS: list[InProcessTool] = [
    JOKE_TOOL,
    CALCULATOR_TOOL,
    WORD_OF_DAY_TOOL,
    REVIEW_WORDS_TOOL,
    DEFINE_WORD_TOOL,
]
