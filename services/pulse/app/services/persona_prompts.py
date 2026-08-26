"""Turns a Persona's dials into a sentence the model can act on.

One phrase per dial rather than one blob per named preset: the dials are independent,
so the combinations are the point, and a lookup table of preset -> paragraph could only
ever describe the combinations someone remembered to write down.
"""
from app.models import Persona

_LENGTH = {
    "brief": "Keep it to a few sentences. Say the most important thing first and stop.",
    "standard": "A few short paragraphs is the right size.",
    "detailed": "Go into detail, covering each strand of work separately.",
}

_AUDIENCE = {
    "executive": "You are writing for an executive who does not follow the day-to-day work.",
    "manager": "You are writing for the engineer's manager, who follows the work but not every commit.",
    "engineer": "You are writing for another engineer on the same codebase.",
}

_TECHNICAL_DEPTH = {
    "low": "Avoid technical terms, tool names and identifiers. Describe outcomes in plain language.",
    "medium": "Use technical terms where they are the clearest way to say something, but explain anything unusual.",
    "high": "Use precise technical language, and name components, files and identifiers where they matter.",
}

_FORMALITY = {
    "casual": "Write plainly and conversationally, the way a colleague would in a message.",
    "neutral": "Write in a straightforward professional register.",
    "formal": "Write formally, in complete sentences, with no contractions or asides.",
}

# Freeform text goes into the prompt as-is, so it is capped: a persona is a tone, not a
# side channel for an unbounded instruction block the caller never pays attention to.
MAX_INSTRUCTIONS_CHARS = 2000

def describe(persona: Persona | None) -> str:
    """The prompt fragment for a persona, or an empty string when there is none."""
    if persona is None:
        return ""
    parts = [
        _AUDIENCE.get(persona.audience),
        _LENGTH.get(persona.length),
        _TECHNICAL_DEPTH.get(persona.technical_depth),
        _FORMALITY.get(persona.formality),
    ]
    instructions = (persona.instructions or "").strip()
    if instructions:
        parts.append(instructions[:MAX_INSTRUCTIONS_CHARS])
    return " ".join(p for p in parts if p)

def apply_to_system_prompt(system_prompt: str, persona: Persona | None) -> str:
    """Appended, never prepended and never a replacement: the base prompt carries the
    rules about not inventing work, and a persona must not be able to talk over them."""
    fragment = describe(persona)
    if not fragment:
        return system_prompt
    return f"{system_prompt}\n\nTone and audience for this piece: {fragment}"
