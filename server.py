from fastapi import FastAPI
from pydantic import BaseModel
from typing import Literal, Optional, List

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


# (Opcional pero recomendado) para que / no dé Not Found
@app.get("/")
def root():
    return {
        "service": "subtitle-worker",
        "status": "ok",
        "endpoints": ["/health", "/subtitle"]
    }


class SubtitleRequest(BaseModel):
    text: str
    format: Literal["srt", "vtt"] = "srt"
    words_per_subtitle: int = 8
    seconds_per_subtitle: float = 2.2
    max_chars_per_line: int = 40


def chunk_words(words: List[str], size: int) -> List[List[str]]:
    return [words[i:i + size] for i in range(0, len(words), size)]


def wrap_line(text: str, max_chars: int) -> str:
    # división simple en 1 o 2 líneas para no pasarte de caracteres
    if len(text) <= max_chars:
        return text
    # corta por espacio cerca del centro
    mid = len(text) // 2
    left = text.rfind(" ", 0, mid)
    right = text.find(" ", mid)
    cut = left if left != -1 else (right if right != -1 else mid)
    return text[:cut].strip() + "\n" + text[cut:].strip()


def srt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def vtt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02}:{m:02}:{s:02}.{ms:03}"


@app.post("/subtitle")
def subtitle(req: SubtitleRequest):
    words = req.text.strip().split()
    if not words:
        return {"format": req.format, "count": 0, "subtitles": ""}

    chunks = chunk_words(words, max(1, req.words_per_subtitle))

    lines = []
    current = 0.0

    if req.format == "vtt":
        lines.append("WEBVTT\n")

    for i, chunk in enumerate(chunks, start=1):
        start = current
        end = current + max(0.2, float(req.seconds_per_subtitle))
        current = end

        text = " ".join(chunk)
        text = wrap_line(text, req.max_chars_per_line)

        if req.format == "srt":
            lines.append(str(i))
            lines.append(f"{srt_timestamp(start)} --> {srt_timestamp(end)}")
            lines.append(text)
            lines.append("")  # línea vacía
        else:
            lines.append(f"{vtt_timestamp(start)} --> {vtt_timestamp(end)}")
            lines.append(text)
            lines.append("")

    return {
        "format": req.format,
        "count": len(chunks),
        "subtitles": "\n".join(lines).strip()
    }
