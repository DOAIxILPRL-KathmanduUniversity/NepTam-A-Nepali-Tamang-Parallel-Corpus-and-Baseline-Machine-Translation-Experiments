#!/usr/bin/env python3
"""
Nepali Audio Studio — backend.

- Reads ../test.csv (read-only, never modified).
- Writes cleaned recordings to ../data/<sentence_id>.mp3 (only mp3 files go there).
- Per-clip metadata (duration, levels, flags) cached in ./recordings_meta.json.

Audio cleanup pipeline (fixes the "click at the end"):
  decode -> drop first 100 ms + last 250 ms (key/mouse click) -> remove DC
  -> trim leading/trailing silence, keep 150 ms padding -> normalize speech
  to -20 dBFS RMS (peak capped at -1 dBFS) -> 30 ms fade in/out -> MP3 192k mono 44.1 kHz

Run:  python3 server.py   ->  http://127.0.0.1:7865
"""

import csv
import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------- paths/config
STUDIO_DIR = Path(__file__).resolve().parent
AUDIO_DIR = STUDIO_DIR.parent
CSV_PATH = AUDIO_DIR / "test.csv"
DATA_DIR = AUDIO_DIR / "data"
META_PATH = STUDIO_DIR / "recordings_meta.json"
STATIC_DIR = STUDIO_DIR / "static"
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

SR = 44100
HEAD_TRIM_S = 0.10   # key-press noise at start
TAIL_TRIM_S = 0.25   # key/mouse click at stop
PAD_S = 0.15         # silence kept around speech
FADE_S = 0.03
FRAME_S = 0.02
TARGET_RMS_DB = -20.0
PEAK_CEIL_DB = -1.0
MAX_BOOST_DB = 30.0

# Quality thresholds
QUIET_DB = -42.0     # raw speech level below this => "quiet"
MIN_DUR_S = 0.6
MAX_DUR_S = 25.0
FAST_CPS = 25.0      # Devanagari code points per second of speech
SLOW_CPS = 3.0

DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- dataset
def load_sentences():
    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for i, r in enumerate(rows):
        out.append({
            "idx": i,
            "id": (r.get("sentence_id") or f"ROW-{i}").strip(),
            "nepali": (r.get("nepali_sentences") or "").strip(),
            "tamang": (r.get("translation_tamang") or "").strip(),
            "type": (r.get("sentence_type") or "Unknown").strip() or "Unknown",
            "tense": (r.get("Tense") or "Unknown").strip() or "Unknown",
            "polarity": (r.get("polarity") or "Unknown").strip() or "Unknown",
        })
    return out


SENTENCES = load_sentences()
TOTAL = len(SENTENCES)
BY_ID = {s["id"]: s for s in SENTENCES}
SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]+$")


def mp3_path(sid: str) -> Path:
    if not SAFE_ID.match(sid):
        raise HTTPException(400, "Unsafe sentence id")
    return DATA_DIR / f"{sid}.mp3"


def recorded_ids() -> set:
    return {p.stem for p in DATA_DIR.glob("*.mp3") if p.stem in BY_ID}


# ---------------------------------------------------------------- metadata
_lock = threading.Lock()


def _load_meta() -> dict:
    if META_PATH.exists():
        try:
            return json.loads(META_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_meta():
    tmp = META_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(META, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(META_PATH)


META = _load_meta()


# ---------------------------------------------------------------- audio utils
def db(v: float) -> float:
    return float(20 * np.log10(max(float(v), 1e-10)))


def decode(src) -> np.ndarray:
    """Decode bytes or a path to mono float32 @ SR."""
    if isinstance(src, (bytes, bytearray)):
        cmd = [FFMPEG, "-v", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", str(SR), "pipe:1"]
        r = subprocess.run(cmd, input=bytes(src), capture_output=True)
    else:
        cmd = [FFMPEG, "-v", "error", "-i", str(src), "-f", "f32le", "-ac", "1", "-ar", str(SR), "pipe:1"]
        r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="ignore")[-400:])
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def encode_mp3(x: np.ndarray, out: Path):
    tmp = out.with_name(out.stem + ".part.mp3")
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0",
           "-codec:a", "libmp3lame", "-b:a", "192k", str(tmp)]
    r = subprocess.run(cmd, input=np.clip(x, -1, 1).astype(np.float32).tobytes(), capture_output=True)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(r.stderr.decode(errors="ignore")[-400:])
    tmp.replace(out)


def frame_rms_db(x: np.ndarray):
    fl = int(FRAME_S * SR)
    n = max(1, x.size // fl)
    fr = x[: n * fl].reshape(n, fl) if x.size >= fl else np.pad(x, (0, fl - x.size)).reshape(1, fl)
    rms = np.sqrt(np.mean(fr.astype(np.float64) ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms), rms, fl


def voiced_frames(rms_db: np.ndarray) -> np.ndarray:
    noise = float(np.percentile(rms_db, 10))
    thr = max(noise + 10.0, float(rms_db.max()) - 35.0, -55.0)
    return np.where(rms_db > thr)[0]


def speech_chars(text: str) -> int:
    return len(re.sub(r"[\s\.\,\?\!\u0964\u0965\-\"'“”‘’:;()]", "", text))


def build_meta(sid, final, raw_level_db, clipped_samples, has_voice, speech_s, ts=None):
    dur = final.size / SR
    s = BY_ID[sid]
    cps = speech_chars(s["nepali"]) / speech_s if speech_s > 0.05 else 0.0
    flags = []
    if not has_voice:
        flags.append("silent")
    if clipped_samples > 10:
        flags.append("clipped")
    if raw_level_db < QUIET_DB:
        flags.append("quiet")
    if dur < MIN_DUR_S:
        flags.append("short")
    if dur > MAX_DUR_S:
        flags.append("long")
    if has_voice and cps > FAST_CPS:
        flags.append("fast")
    if has_voice and 0 < cps < SLOW_CPS:
        flags.append("slow")
    return {
        "duration": round(float(dur), 3),
        "speech_seconds": round(float(speech_s), 3),
        "level_db": round(float(raw_level_db), 1),
        "clipped_samples": int(clipped_samples),
        "chars_per_sec": round(float(cps), 1),
        "flags": flags,
        "recorded_at": ts or datetime.now().isoformat(timespec="seconds"),
    }


def process_take(sid: str, raw: np.ndarray):
    """Clean a raw take; returns (final_audio, meta)."""
    h, t = int(HEAD_TRIM_S * SR), int(TAIL_TRIM_S * SR)
    x = raw[h: max(h, raw.size - t)].astype(np.float64)
    if x.size < int(0.2 * SR):
        raise ValueError("Recording too short — hold for at least half a second.")
    x -= x.mean()

    rms_db, rms, fl = frame_rms_db(x)
    v = voiced_frames(rms_db)
    has_voice = v.size > 0 and float(rms_db.max()) > -60
    pad = int(PAD_S * SR)
    if has_voice:
        start = max(0, v[0] * fl - pad)
        end = min(x.size, (v[-1] + 1) * fl + pad)
        speech_s = (v[-1] - v[0] + 1) * fl / SR
        level = db(np.sqrt(np.mean(rms[v] ** 2)))
        x = x[start:end]
    else:
        start, end = 0, x.size
        speech_s = 0.0
        level = db(np.sqrt(np.mean(x ** 2)))

    clipped = int(np.sum(np.abs(x) >= 0.999))
    peak = db(np.max(np.abs(x))) if x.size else -100
    gain = min(TARGET_RMS_DB - level, PEAK_CEIL_DB - peak, MAX_BOOST_DB)
    x = x * (10 ** (gain / 20))

    nf = min(int(FADE_S * SR), x.size // 4)
    if nf > 1:
        ramp = np.linspace(0.0, 1.0, nf)
        x[:nf] *= ramp
        x[-nf:] *= ramp[::-1]

    final = x.astype(np.float32)
    return final, build_meta(sid, final, level, clipped, has_voice, speech_s)


def analyze_existing(sid: str) -> dict:
    """Metadata for an mp3 that has no cached entry (already processed or external)."""
    p = mp3_path(sid)
    x = decode(p)
    rms_db, rms, fl = frame_rms_db(x)
    v = voiced_frames(rms_db)
    has_voice = v.size > 0
    level = db(np.sqrt(np.mean(rms[v] ** 2))) if has_voice else db(np.sqrt(np.mean(x ** 2)))
    speech_s = (v[-1] - v[0] + 1) * fl / SR if has_voice else 0.0
    ts = datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
    return build_meta(sid, x, level, int(np.sum(np.abs(x) >= 0.999)), has_voice, speech_s, ts)


def sync_meta():
    rec = recorded_ids()
    changed = False
    with _lock:
        for sid in list(META):
            if sid not in rec:
                META.pop(sid)
                changed = True
        for sid in rec:
            if sid not in META:
                try:
                    META[sid] = analyze_existing(sid)
                    changed = True
                except Exception as e:  # noqa
                    print(f"[sync] could not analyze {sid}: {e}")
        if changed:
            _save_meta()


# ---------------------------------------------------------------- app
app = FastAPI(title="Nepali Audio Studio")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def sentence_payload(s: dict, rec: set) -> dict:
    out = dict(s)
    out["recorded"] = s["id"] in rec
    out["meta"] = META.get(s["id"]) if out["recorded"] else None
    return out


def next_unrecorded_idx(after: int, rec: set):
    for k in range(1, TOTAL + 1):
        i = (after + k) % TOTAL
        if SENTENCES[i]["id"] not in rec:
            return i
    return None


@app.get("/")
def root():
    return RedirectResponse("/record")


@app.get("/record")
def page_record():
    return FileResponse(STATIC_DIR / "record.html")


@app.get("/dashboard")
def page_dashboard():
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/review")
def page_review():
    return FileResponse(STATIC_DIR / "review.html")


@app.get("/api/sentence")
def api_sentence(idx: int | None = None, id: str | None = None):
    rec = recorded_ids()
    if id is not None:
        if id not in BY_ID:
            raise HTTPException(404, f"Unknown id {id}")
        s = BY_ID[id]
    elif idx is not None:
        s = SENTENCES[max(0, min(TOTAL - 1, idx))]
    else:
        i = next_unrecorded_idx(-1, rec)
        s = SENTENCES[i if i is not None else 0]
    p = sentence_payload(s, rec)
    p["total"] = TOTAL
    p["recorded_count"] = len(rec)
    p["next_unrecorded"] = next_unrecorded_idx(s["idx"], rec)
    return p


@app.get("/api/next_unrecorded")
def api_next_unrecorded(after: int = -1):
    return {"idx": next_unrecorded_idx(after, recorded_ids())}


@app.post("/api/record/{sid}")
async def api_record(sid: str, file: UploadFile = File(...)):
    if sid not in BY_ID:
        raise HTTPException(404, f"Unknown id {sid}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty upload")
    try:
        raw = decode(data)
        final, meta = process_take(sid, raw)
        encode_mp3(final, mp3_path(sid))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except RuntimeError as e:
        raise HTTPException(500, f"ffmpeg failed: {e}")
    with _lock:
        META[sid] = meta
        _save_meta()
    rec = recorded_ids()
    return {"ok": True, "id": sid, "meta": meta, "recorded_count": len(rec),
            "next_unrecorded": next_unrecorded_idx(BY_ID[sid]["idx"], rec)}


@app.delete("/api/record/{sid}")
def api_delete(sid: str):
    p = mp3_path(sid)
    existed = p.exists()
    p.unlink(missing_ok=True)
    with _lock:
        if META.pop(sid, None) is not None:
            _save_meta()
    return {"ok": True, "deleted": existed}


@app.get("/api/audio/{sid}")
def api_audio(sid: str):
    p = mp3_path(sid)
    if not p.exists():
        raise HTTPException(404, "Not recorded")
    return FileResponse(p, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/filters")
def api_filters():
    return {k: sorted({s[k] for s in SENTENCES}) for k in ("type", "tense", "polarity")}


@app.get("/api/list")
def api_list(status: str = "all", q: str = "", type: str = "", tense: str = "",
             polarity: str = "", flag: str = "", page: int = 1, size: int = Query(50, le=200)):
    rec = recorded_ids()
    ql = q.strip().lower()
    items = []
    for s in SENTENCES:
        r = s["id"] in rec
        m = META.get(s["id"]) if r else None
        flags = (m or {}).get("flags", [])
        if status == "recorded" and not r:
            continue
        if status == "pending" and r:
            continue
        if status == "flagged" and not flags:
            continue
        if flag and flag not in flags:
            continue
        if type and s["type"] != type:
            continue
        if tense and s["tense"] != tense:
            continue
        if polarity and s["polarity"] != polarity:
            continue
        if ql and ql not in s["id"].lower() and ql not in s["nepali"].lower() and ql not in s["tamang"].lower():
            continue
        items.append({**s, "recorded": r, "meta": m})
    total = len(items)
    page = max(1, page)
    return {"total": total, "page": page, "size": size,
            "pages": max(1, (total + size - 1) // size),
            "items": items[(page - 1) * size: page * size]}


@app.get("/api/stats")
def api_stats():
    rec = recorded_ids()
    metas = {sid: META[sid] for sid in rec if sid in META}
    durs = [m["duration"] for m in metas.values()]
    total_s = float(sum(durs))
    avg_s = total_s / len(durs) if durs else 0.0

    breakdown = {}
    for key in ("type", "tense", "polarity"):
        d = {}
        for s in SENTENCES:
            e = d.setdefault(s[key], {"total": 0, "recorded": 0})
            e["total"] += 1
            e["recorded"] += s["id"] in rec
        breakdown[key] = d

    today = datetime.now().date()
    per_day = {(today - timedelta(days=k)).isoformat(): 0 for k in range(13, -1, -1)}
    for m in metas.values():
        d = m["recorded_at"][:10]
        if d in per_day:
            per_day[d] += 1

    streak = 0
    for k in range(0, 365):
        d = (today - timedelta(days=k)).isoformat()
        if any(m["recorded_at"].startswith(d) for m in metas.values()):
            streak += 1
        elif k > 0:
            break

    flag_counts = {}
    for m in metas.values():
        for f in m.get("flags", []):
            flag_counts[f] = flag_counts.get(f, 0) + 1

    recent = sorted(metas.items(), key=lambda kv: kv[1]["recorded_at"], reverse=True)[:10]
    pending = TOTAL - len(rec)
    return {
        "total": TOTAL,
        "recorded": len(rec),
        "pending": pending,
        "pct": round(len(rec) / TOTAL * 100, 2) if TOTAL else 0,
        "total_seconds": round(total_s, 1),
        "avg_seconds": round(avg_s, 2),
        "est_remaining_seconds": round(pending * avg_s, 1),
        "today": per_day[today.isoformat()],
        "streak_days": streak,
        "per_day": per_day,
        "breakdown": breakdown,
        "flags": flag_counts,
        "flagged_total": sum(1 for m in metas.values() if m.get("flags")),
        "recent": [{"id": sid, "idx": BY_ID[sid]["idx"], "nepali": BY_ID[sid]["nepali"], **m}
                   for sid, m in recent],
    }


sync_meta()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7865))
    print(f"Nepali Audio Studio → http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
