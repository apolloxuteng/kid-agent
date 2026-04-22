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
    ("analyze", "to look closely at something so you can understand it better", "We can analyze a puzzle by checking one piece at a time."),
    ("predict", "to make a smart guess about what might happen next", "Dark clouds can help us predict that rain may be coming."),
    ("evidence", "clues or facts that help show whether an idea is true", "Footprints are evidence that someone walked through the mud."),
    ("strategy", "a plan you use to solve a problem or win a game", "Her chess strategy was to protect her king first."),
    ("contrast", "to compare things by noticing how they are different", "We can contrast summer and winter by talking about heat and snow."),
    ("compare", "to look at two things and notice how they are alike or different", "You can compare two books by thinking about their characters."),
    ("estimate", "to make a careful guess that is close to the real answer", "I estimate there are about fifty jelly beans in the jar."),
    ("consequence", "what happens because of an action or choice", "A consequence of staying up late is feeling tired the next morning."),
    ("efficient", "working well without wasting time or effort", "Packing your backpack the night before is an efficient way to get ready."),
    ("adapt", "to change so you can handle a new situation", "Animals adapt to winter by growing thicker fur or finding shelter."),
    ("investigate", "to look carefully for facts or clues", "The class investigated why the plant near the window grew faster."),
    ("communicate", "to share ideas or information with others", "You can communicate by speaking, writing, drawing, or using gestures."),
    ("perspective", "one person's way of seeing or thinking about something", "From my perspective, the hill looked huge."),
    ("solution", "an answer or method that fixes a problem", "The solution was to tighten the loose screw."),
    ("pattern", "something that repeats in a way you can notice", "Red, blue, red, blue is a color pattern."),
    ("resourceful", "good at finding clever ways to solve problems", "A resourceful builder used cardboard to make a robot arm."),
    ("precise", "very exact and careful", "A recipe needs precise measurements so the cake turns out right."),
    ("temporary", "lasting for only a short time", "The blanket fort was temporary because we took it down after dinner."),
    ("permanent", "meant to last for a long time", "A tree's roots are more permanent than footprints in sand."),
    ("cooperate", "to work together toward the same goal", "The team had to cooperate to build the tallest tower."),
    ("curious", "wanting to learn or know more about something", "A curious scientist asks questions and tests ideas."),
    ("observe", "to look carefully and notice details", "You can observe a snail's trail after it moves across a rock."),
    ("summarize", "to tell the main idea in a shorter way", "After reading the chapter, she summarized what happened in three sentences."),
    ("infer", "to figure something out using clues", "If the floor is wet and someone has an umbrella, you might infer it rained."),
    ("accurate", "correct and close to the truth", "An accurate map helps you find the right trail."),
    ("flexible", "able to change plans when needed", "A flexible teammate can try a new position during the game."),
    ("confident", "believing you can try something or handle a challenge", "He felt confident after practicing the song many times."),
    ("complex", "made of many connected parts", "A city is complex because roads, people, buildings, and rules all work together."),
    ("fragile", "easy to break or damage", "A glass ornament is fragile, so we carry it carefully."),
    ("essential", "very important and needed", "Water is essential for plants to grow."),
)

LOCAL_DEFINITION_BANK: tuple[tuple[str, str, str], ...] = WORD_BANK + (
    ("sophisticated", "smart, advanced, or carefully made with many thoughtful details", "The robot used a sophisticated sensor to avoid bumping into the wall."),
    ("independent", "able to do something or think for yourself without needing much help", "She became more independent after learning how to pack her own school bag."),
    ("responsible", "trusted to make good choices and take care of what you need to do", "A responsible teammate remembers practice and helps clean up."),
    ("generous", "willing to share time, help, or things with other people", "He was generous when he let his friend use the last marker."),
    ("determined", "not giving up, even when something is difficult", "She was determined to finish the puzzle before dinner."),
    ("patient", "able to wait or keep trying without getting upset", "A patient builder fixes one mistake at a time."),
    ("convince", "to help someone believe or agree with an idea by giving reasons", "He tried to convince his parents that the plan was safe."),
    ("explain", "to make an idea clear so someone can understand it", "The teacher used a drawing to explain how shadows work."),
    ("describe", "to tell what something is like using details", "Can you describe the creature you imagined?"),
    ("protect", "to keep someone or something safe from harm", "A helmet helps protect your head when you ride a bike."),
    ("discover", "to find or learn something for the first time", "The class discovered tiny sprouts growing in the soil."),
    ("imagine", "to make pictures or ideas in your mind", "You can imagine a city floating above the clouds."),
    ("creative", "good at making new ideas, stories, designs, or solutions", "Her creative plan turned two boxes into a castle."),
    ("challenge", "something difficult that gives you a chance to learn or improve", "The hard level in the game was a real challenge."),
    ("focus", "to pay close attention to one thing", "He needed to focus so he could hear every note in the song."),
    ("organize", "to arrange things in a clear and useful way", "We organize the cards by color before starting the game."),
    ("conflict", "a disagreement or problem between people, ideas, or goals", "The story's conflict began when both teams wanted the same field."),
    ("solution", "an answer or method that fixes a problem", "The solution was to tighten the loose screw."),
    ("curious", "wanting to learn or know more about something", "A curious scientist asks questions and tests ideas."),
    ("complex", "made of many connected parts", "A city is complex because roads, people, buildings, and rules all work together."),
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


def _parse_definition_json(text: str) -> dict | None:
    """Parse JSON from plain output or markdown-fenced output."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _definition_from_bank(word: str) -> tuple[str, str, str] | None:
    normalized = word.strip().lower()
    for candidate, meaning, example in LOCAL_DEFINITION_BANK:
        if candidate.lower() == normalized:
            return candidate, meaning, example
    return None


async def _definition_from_learned_words(profile_id: str, word: str) -> tuple[str, str, str] | None:
    learned = await asyncio.to_thread(db.load_learned_words, profile_id, 500)
    normalized = word.strip().lower()
    for item in learned:
        learned_word = (item.get("word") or "").strip().lower()
        if learned_word == normalized:
            return (
                item.get("word") or word,
                item.get("meaning") or f"the meaning of the word {word}",
                item.get("example") or f"I learned the word {word} today.",
            )
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
        learned = await asyncio.to_thread(db.load_learned_words, ctx.profile_id, 500)
        learned_words = {item.get("word", "").lower() for item in learned}
        fresh_words = [entry for entry in WORD_BANK if entry[0].lower() not in learned_words]
        word, meaning, example = random.choice(fresh_words or list(WORD_BANK))
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

        learned_definition = await _definition_from_learned_words(ctx.profile_id, word)
        if learned_definition:
            word, meaning, example = learned_definition
            logger.info("Definition served from learned words: word=%s", word)
            return ToolResult(text=f"{word.capitalize()} means {meaning}. Example: {example}")

        local_definition = _definition_from_bank(word)
        if local_definition:
            word, meaning, example = local_definition
            saved = await asyncio.to_thread(db.save_learned_word, ctx.profile_id, word, meaning, example)
            if not saved:
                logger.warning("Failed to store local defined word for profile_id=%s word=%s", ctx.profile_id, word)
            logger.info("Definition served from local bank: word=%s", word)
            return ToolResult(text=f"{word.capitalize()} means {meaning}. Example: {example}")

        fallback_meaning = f"the meaning of the word {word}"
        fallback_example = f"I learned the word {word} today."
        prompt = (
            "Explain one English vocabulary word for a curious 7-year-old. "
            "Return only JSON with keys word, meaning, example. "
            "The meaning should be one clear sentence. The example should be one natural sentence using the word. "
            f"Word: {word}"
        )
        data = await llm.call_ollama(prompt, timeout=12, raise_on_error=False)
        meaning = fallback_meaning
        example = fallback_example
        if data:
            parsed = _parse_definition_json(data)
            if parsed:
                parsed_word = str(parsed.get("word") or word).strip().lower()
                if parsed_word:
                    word = re.sub(r"[^a-zA-Z\-']", "", parsed_word).lower() or word
                parsed_meaning = str(parsed.get("meaning") or "").strip()
                parsed_example = str(parsed.get("example") or "").strip()
                if parsed_meaning:
                    meaning = parsed_meaning
                if parsed_example:
                    example = parsed_example
            else:
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
