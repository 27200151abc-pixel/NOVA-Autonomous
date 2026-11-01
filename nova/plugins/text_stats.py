PLUGIN = {
    "name": "text_stats",
    "description": "Count words, characters, and lines in supplied text.",
    "parameters": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False
    }
}


def run(arguments):
    text = str(arguments.get("text", ""))
    return {"characters": len(text), "words": len(text.split()), "lines": len(text.splitlines()) or (1 if text else 0)}
