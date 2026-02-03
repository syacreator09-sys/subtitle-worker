from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, FileResponse
import os, uuid, subprocess, tempfile

app = FastAPI()

@app.get("/")
def root():
    return {"service": "subtitle-worker", "status": "ok", "endpoints": ["/health", "/subtitle", "/burn"]}

@app.get("/health")
def health():
    return {"status": "ok"}

def make_srt(text: str, words_per_subtitle: int = 7, seconds_per_subtitle: float = 2.2, max_chars_per_line: int = 38):
    # súper simple: parte por palabras y asigna duraciones fijas
    words = text.strip().split()
    chunks = [words[i:i+words_per_subtitle] for i in range(0, len(words), words_per_subtitle)]

    def wrap_line(s: str, max_len: int):
        # wrap básico por longitud
        out, line = [], ""
        for w in s.split():
            if len((line + " " + w).strip()) <= max_len:
                line = (line + " " + w).strip()
            else:
                out.append(line)
                line = w
        if line:
            out.append(line)
        return "\n".join(out)

    srt_lines = []
    t0 = 0.0
    idx = 1
    for chunk in chunks:
        t1 = t0 + seconds_per_subtitle
        phrase = " ".join(chunk)
        phrase = wrap_line(phrase, max_chars_per_line)

        def fmt(t):
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = int(t % 60)
            ms = int(round((t - int(t)) * 1000))
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        srt_lines.append(str(idx))
        srt_lines.append(f"{fmt(t0)} --> {fmt(t1)}")
        srt_lines.append(phrase)
        srt_lines.append("")
        idx += 1
        t0 = t1

    return "\n".join(srt_lines), len(chunks)

@app.post("/subtitle")
def subtitle(payload: dict):
    text = payload.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing 'text'")

    fmt = payload.get("format", "srt").lower()
    wps = int(payload.get("words_per_subtitle", 7))
    sps = float(payload.get("seconds_per_subtitle", 2.2))
    maxc = int(payload.get("max_chars_per_line", 38))

    srt, count = make_srt(text, wps, sps, maxc)
    return {"format": fmt, "count": count, "subtitles": srt}

@app.post("/burn")
async def burn(
    video: UploadFile = File(...),
    text: str = Form(""),
    srt: str = Form(""),
    # estilo “padre” default
    font_size: int = Form(48),
    outline: int = Form(4),
    shadow: int = Form(1),
    margin_v: int = Form(80),
):
    if not video.filename:
        raise HTTPException(status_code=400, detail="Missing video file")

    # temp folder
    job_id = uuid.uuid4().hex
    tmp_dir = tempfile.mkdtemp(prefix=f"sub_{job_id}_")

    in_path = os.path.join(tmp_dir, "input.mp4")
    srt_path = os.path.join(tmp_dir, "subtitles.srt")
    out_path = os.path.join(tmp_dir, "output.mp4")

    # guarda video
    content = await video.read()
    with open(in_path, "wb") as f:
        f.write(content)

    # genera srt si no viene
    if not srt.strip():
        if not text.strip():
            raise HTTPException(status_code=400, detail="Provide 'text' or 'srt'")
        generated_srt, _ = make_srt(text, 7, 2.2, 38)
        srt = generated_srt

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt)

    # estilo ASS via force_style (se aplica sobre SRT render)
    # BorderStyle=3 -> caja transparente detrás (más legible en TikTok)
    force_style = (
        f"FontName=DejaVu Sans,"
        f"FontSize={font_size},"
        f"PrimaryColour=&H00FFFFFF,"   # blanco
        f"OutlineColour=&H00000000,"   # negro
        f"BackColour=&H64000000,"      # fondo semitransparente
        f"Bold=1,"
        f"BorderStyle=3,"
        f"Outline={outline},"
        f"Shadow={shadow},"
        f"MarginV={margin_v},"
        f"Alignment=2"                 # bottom-center
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", in_path,
        "-vf", f"subtitles={srt_path}:force_style='{force_style}'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "copy",
        out_path
    ]

    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise HTTPException(status_code=500, detail=f"FFmpeg failed: {p.stderr[-1200:]}")

    # devuelve el mp4
    return FileResponse(out_path, media_type="video/mp4", filename="subtitled.mp4")
