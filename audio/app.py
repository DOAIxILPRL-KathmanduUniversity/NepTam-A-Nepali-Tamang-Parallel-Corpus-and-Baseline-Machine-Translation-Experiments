#!/usr/bin/env python3
"""
Nepali Audio Recording & Annotation Studio
Target: Record audio for Nepali sentences from test.csv and save to audio/data/<sentence_id>.mp3
"""

import os
import csv
import shutil
import subprocess
from pathlib import Path
import gradio as gr

# Directories
BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "test.csv"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Find ffmpeg binary
FFMPEG_BIN = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def load_dataset():
    """Load sentences from test.csv (without modifying it)."""
    sentences = []
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"test.csv not found at {CSV_PATH}")

    with open(CSV_PATH, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            sentences.append({
                "idx": idx,
                "sentence_id": row.get("sentence_id", f"ID-{idx}"),
                "nepali": row.get("nepali_sentences", "").strip(),
                "tamang": row.get("translation_tamang", "").strip(),
                "sentence_type": row.get("sentence_type", "").strip(),
                "tense": row.get("Tense", "").strip(),
                "polarity": row.get("polarity", "").strip(),
            })
    return sentences


DATASET = load_dataset()
TOTAL_COUNT = len(DATASET)
ID_TO_INDEX = {item["sentence_id"]: item["idx"] for item in DATASET}


def is_recorded(sentence_id: str) -> bool:
    """Check if mp3 audio file exists for the given sentence_id."""
    return (DATA_DIR / f"{sentence_id}.mp3").exists()


def get_audio_path(sentence_id: str) -> str | None:
    """Return string path to audio file if it exists, else None."""
    p = DATA_DIR / f"{sentence_id}.mp3"
    return str(p) if p.exists() else None


def get_stats():
    """Calculate recording statistics."""
    recorded_count = sum(1 for item in DATASET if is_recorded(item["sentence_id"]))
    unrecorded_count = TOTAL_COUNT - recorded_count
    pct = (recorded_count / TOTAL_COUNT * 100) if TOTAL_COUNT > 0 else 0
    return recorded_count, unrecorded_count, pct


def get_filtered_indices(filter_mode: str):
    """Filter indices based on mode: All, Unrecorded Only, Recorded Only."""
    if filter_mode == "Unrecorded Only":
        indices = [i for i, item in enumerate(DATASET) if not is_recorded(item["sentence_id"])]
        return indices if indices else [0]
    elif filter_mode == "Recorded Only":
        indices = [i for i, item in enumerate(DATASET) if is_recorded(item["sentence_id"])]
        return indices if indices else [0]
    return list(range(TOTAL_COUNT))


def get_sentence_state(current_idx: int, filter_mode: str = "All"):
    """Prepare all UI components for the sentence at current_idx."""
    if current_idx < 0:
        current_idx = 0
    elif current_idx >= TOTAL_COUNT:
        current_idx = TOTAL_COUNT - 1

    item = DATASET[current_idx]
    s_id = item["sentence_id"]
    nepali_text = item["nepali"]
    tamang_text = item["tamang"]
    s_type = item["sentence_type"] or "N/A"
    tense = item["tense"] or "N/A"
    polarity = item["polarity"] or "N/A"

    recorded = is_recorded(s_id)
    audio_file = get_audio_path(s_id)

    rec_count, unrec_count, pct = get_stats()

    # Status badge styling
    if recorded:
        status_html = (
            f"<div style='display:inline-flex; align-items:center; gap:6px; "
            f"background:rgba(34, 197, 94, 0.15); border:1px solid #22c55e; "
            f"color:#22c55e; font-weight:600; padding:6px 14px; border-radius:20px; font-size:14px;'>"
            f"<span>●</span> <span>RECORDED ({s_id}.mp3)</span></div>"
        )
    else:
        status_html = (
            f"<div style='display:inline-flex; align-items:center; gap:6px; "
            f"background:rgba(234, 179, 8, 0.15); border:1px solid #eab308; "
            f"color:#eab308; font-weight:600; padding:6px 14px; border-radius:20px; font-size:14px;'>"
            f"<span>○</span> <span>PENDING RECORDING</span></div>"
        )

    # Main Nepali sentence card display
    sentence_html = f"""
    <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); 
                border: 1px solid #334155; border-radius: 16px; padding: 28px; 
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3); text-align: center; margin: 10px 0;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
            <span style="background:#3b82f6; color:#ffffff; font-weight:700; font-size:14px; 
                         padding:4px 12px; border-radius:12px; letter-spacing:0.5px;">
                ID: {s_id}
            </span>
            <span style="color:#94a3b8; font-size:14px; font-weight:500;">
                Index: {current_idx + 1} / {TOTAL_COUNT}
            </span>
            {status_html}
        </div>
        
        <div style="font-family: 'Mukta', 'Noto Sans Devanagari', -apple-system, sans-serif; 
                    font-size: 38px; font-weight: 700; color: #f8fafc; line-height: 1.5; 
                    letter-spacing: 0.5px; padding: 20px 10px; text-shadow: 0 2px 4px rgba(0,0,0,0.5);">
            {nepali_text}
        </div>

        <div style="display:flex; justify-content:center; gap:12px; flex-wrap:wrap; margin-top:14px;">
            <span style="background:#1e293b; border:1px solid #475569; color:#cbd5e1; font-size:12px; padding:4px 10px; border-radius:8px;">
                Type: {s_type}
            </span>
            <span style="background:#1e293b; border:1px solid #475569; color:#cbd5e1; font-size:12px; padding:4px 10px; border-radius:8px;">
                Tense: {tense}
            </span>
            <span style="background:#1e293b; border:1px solid #475569; color:#cbd5e1; font-size:12px; padding:4px 10px; border-radius:8px;">
                Polarity: {polarity}
            </span>
        </div>
    </div>
    """

    stats_html = f"""
    <div style="display:flex; justify-content:space-around; align-items:center; 
                background:#0f172a; border:1px solid #1e293b; border-radius:12px; 
                padding:12px; margin-bottom:10px; font-family:sans-serif;">
        <div style="text-align:center;">
            <div style="font-size:22px; font-weight:700; color:#60a5fa;">{TOTAL_COUNT}</div>
            <div style="font-size:11px; text-transform:uppercase; color:#94a3b8; letter-spacing:0.5px;">Total Sentences</div>
        </div>
        <div style="border-left:1px solid #334155; height:32px;"></div>
        <div style="text-align:center;">
            <div style="font-size:22px; font-weight:700; color:#22c55e;">{rec_count}</div>
            <div style="font-size:11px; text-transform:uppercase; color:#94a3b8; letter-spacing:0.5px;">Recorded</div>
        </div>
        <div style="border-left:1px solid #334155; height:32px;"></div>
        <div style="text-align:center;">
            <div style="font-size:22px; font-weight:700; color:#eab308;">{unrec_count}</div>
            <div style="font-size:11px; text-transform:uppercase; color:#94a3b8; letter-spacing:0.5px;">Pending</div>
        </div>
        <div style="border-left:1px solid #334155; height:32px;"></div>
        <div style="text-align:center;">
            <div style="font-size:22px; font-weight:700; color:#a855f7;">{pct:.1f}%</div>
            <div style="font-size:11px; text-transform:uppercase; color:#94a3b8; letter-spacing:0.5px;">Completed</div>
        </div>
    </div>
    """

    # Existing audio preview
    existing_audio = audio_file if recorded else None

    # Reset mic input
    return (
        current_idx,
        sentence_html,
        stats_html,
        tamang_text,
        existing_audio,
        None,  # Reset mic input component
        f"Ready. Currently at sentence #{current_idx + 1} ({s_id})"
    )


def save_and_advance(current_idx: int, audio_path: str | None, filter_mode: str, advance_to_next: bool = True):
    """Save recorded audio as data/<sentence_id>.mp3 using ffmpeg, then navigate."""
    if not audio_path or not os.path.exists(audio_path):
        return (
            current_idx,
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            "⚠️ No audio recorded! Please record audio via microphone first."
        )

    item = DATASET[current_idx]
    s_id = item["sentence_id"]
    output_mp3 = DATA_DIR / f"{s_id}.mp3"

    try:
        # Convert recorded audio to high quality standard MP3 (44.1kHz mono 192k)
        cmd = [
            FFMPEG_BIN, "-y",
            "-i", str(audio_path),
            "-vn",
            "-ar", "44100",
            "-ac", "1",
            "-b:a", "192k",
            str(output_mp3)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return (
                current_idx,
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                f"❌ FFmpeg conversion failed: {res.stderr}"
            )
    except Exception as e:
        return (
            current_idx,
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            f"❌ Error saving audio: {str(e)}"
        )

    # Next index calculation
    next_idx = current_idx
    if advance_to_next:
        indices = get_filtered_indices(filter_mode)
        try:
            curr_pos = indices.index(current_idx)
            if curr_pos + 1 < len(indices):
                next_idx = indices[curr_pos + 1]
            else:
                next_idx = indices[0]
        except ValueError:
            next_idx = (current_idx + 1) % TOTAL_COUNT

    # Return refreshed UI for next_idx
    c_idx, s_html, st_html, tamang, exist_aud, mic_val, _ = get_sentence_state(next_idx, filter_mode)
    msg = f"✅ Saved {s_id}.mp3 successfully! Moved to sentence #{next_idx + 1}."
    return c_idx, s_html, st_html, tamang, exist_aud, mic_val, msg


def delete_recording(current_idx: int, filter_mode: str):
    """Delete existing mp3 for current sentence."""
    item = DATASET[current_idx]
    s_id = item["sentence_id"]
    target_mp3 = DATA_DIR / f"{s_id}.mp3"
    if target_mp3.exists():
        target_mp3.unlink()
        msg = f"🗑️ Deleted recording for {s_id}."
    else:
        msg = f"ℹ️ No existing recording found for {s_id}."

    c_idx, s_html, st_html, tamang, exist_aud, mic_val, _ = get_sentence_state(current_idx, filter_mode)
    return c_idx, s_html, st_html, tamang, exist_aud, mic_val, msg


def navigate(current_idx: int, direction: str, filter_mode: str):
    """Navigate sentences based on filter and direction."""
    indices = get_filtered_indices(filter_mode)
    if not indices:
        indices = [0]

    if direction == "first":
        next_idx = indices[0]
    elif direction == "last":
        next_idx = indices[-1]
    elif direction == "prev":
        if current_idx in indices:
            pos = indices.index(current_idx)
            next_idx = indices[pos - 1] if pos > 0 else indices[0]
        else:
            prev_candidates = [i for i in indices if i < current_idx]
            next_idx = prev_candidates[-1] if prev_candidates else indices[0]
    elif direction == "next":
        if current_idx in indices:
            pos = indices.index(current_idx)
            next_idx = indices[pos + 1] if pos + 1 < len(indices) else indices[-1]
        else:
            next_candidates = [i for i in indices if i > current_idx]
            next_idx = next_candidates[0] if next_candidates else indices[-1]
    elif direction == "next_unrecorded":
        unrec = [i for i, item in enumerate(DATASET) if not is_recorded(item["sentence_id"])]
        if not unrec:
            return get_sentence_state(current_idx, filter_mode)
        # Find next unrecorded after current_idx
        following = [i for i in unrec if i > current_idx]
        next_idx = following[0] if following else unrec[0]
    else:
        next_idx = current_idx

    return get_sentence_state(next_idx, filter_mode)


def jump_to_sentence_id(target_id: str, filter_mode: str):
    """Jump directly to a sentence ID."""
    target_id = target_id.strip()
    if target_id in ID_TO_INDEX:
        return get_sentence_state(ID_TO_INDEX[target_id], filter_mode)
    return get_sentence_state(0, filter_mode)


def build_app():
    custom_css = """
    @import url('https://fonts.googleapis.com/css2?family=Mukta:wght@400;600;700;800&family=Outfit:wght@400;500;600;700&display=swap');
    
    body, .gradio-container {
        font-family: 'Outfit', -apple-system, sans-serif !important;
        background-color: #0b0f19 !important;
        color: #f1f5f9 !important;
    }
    .main-header {
        text-align: center;
        margin-top: 8px;
        margin-bottom: 12px;
    }
    .action-btn {
        font-weight: 600 !important;
        border-radius: 10px !important;
        transition: all 0.2s ease-in-out !important;
    }
    .primary-save-btn {
        background: linear-gradient(135deg, #2563eb, #1d4ed8) !important;
        color: white !important;
        font-size: 16px !important;
        box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4) !important;
    }
    .primary-save-btn:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 20px rgba(37, 99, 235, 0.6) !important;
    }
    """

    with gr.Blocks(title="Nepali Audio Annotation Studio") as demo:
        # State tracking
        current_idx_state = gr.State(0)
        # State tracking
        current_idx_state = gr.State(0)

        with gr.Row():
            with gr.Column():
                gr.HTML("""
                <div class="main-header">
                    <h1 style="font-size: 26px; font-weight: 800; color: #60a5fa; margin: 0; letter-spacing: -0.5px;">
                        🎙️ Nepali Speech Recording & Annotation Studio
                    </h1>
                    <p style="font-size: 13px; color: #94a3b8; margin: 4px 0 0 0;">
                        Focus: <b>nepali_sentences</b> &nbsp;|&nbsp; Target Output: <code>audio/data/&lt;sentence_id&gt;.mp3</code>
                    </p>
                </div>
                """)

        # Stats Header
        stats_display = gr.HTML()

        # Nepali Sentence Card
        sentence_display = gr.HTML()

        # Audio Section
        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 🎤 1. Record Audio (Microphone)")
                mic_input = gr.Audio(
                    sources=["microphone"],
                    type="filepath",
                    label="Click microphone icon to record. Click stop when finished.",
                    waveform_options=gr.WaveformOptions(
                        waveform_color="#3b82f6",
                        waveform_progress_color="#1d4ed8",
                        show_recording_waveform=True
                    )
                )

                with gr.Row():
                    save_next_btn = gr.Button(
                        "💾 Save & Next Unrecorded ⏭️",
                        variant="primary",
                        elem_classes=["action-btn", "primary-save-btn"],
                        scale=2
                    )
                    save_stay_btn = gr.Button(
                        "💾 Save Only",
                        variant="secondary",
                        elem_classes=["action-btn"],
                        scale=1
                    )

            with gr.Column(scale=1):
                gr.Markdown("### 🔊 2. Current Saved Audio (`data/<id>.mp3`)")
                existing_audio_player = gr.Audio(
                    label="Saved Recording Playback",
                    type="filepath",
                    interactive=False
                )
                delete_btn = gr.Button(
                    "🗑️ Delete / Retake Recording",
                    variant="stop",
                    elem_classes=["action-btn"]
                )

                with gr.Accordion("📖 Reference: Tamang Translation", open=False):
                    tamang_display = gr.Textbox(
                        label="Tamang Reference",
                        interactive=False,
                        lines=2
                    )

        # Navigation Bar & Controls
        with gr.Row():
            prev_btn = gr.Button("◀️ Prev", elem_classes=["action-btn"], scale=1)
            next_unrec_btn = gr.Button("⚡ Next Unrecorded ⏭️", variant="secondary", elem_classes=["action-btn"], scale=2)
            next_btn = gr.Button("Next ▶️", elem_classes=["action-btn"], scale=1)

        with gr.Row():
            filter_dropdown = gr.Dropdown(
                choices=["All", "Unrecorded Only", "Recorded Only"],
                value="All",
                label="Filter View",
                interactive=True,
                scale=1
            )
            index_input = gr.Number(
                value=1,
                label=f"Jump to Index (1 - {TOTAL_COUNT})",
                precision=0,
                minimum=1,
                maximum=TOTAL_COUNT,
                interactive=True,
                scale=1
            )
            id_search_input = gr.Dropdown(
                choices=[item["sentence_id"] for item in DATASET],
                value=DATASET[0]["sentence_id"],
                label="Jump to Sentence ID",
                allow_custom_value=True,
                interactive=True,
                scale=2
            )

        # Status / Feedback log
        status_log = gr.Markdown("Ready to record.")

        # Event Handlers
        # Save & Next (Unrecorded)
        save_next_btn.click(
            fn=lambda idx, aud, filt: save_and_advance(idx, aud, filt, advance_to_next=True),
            inputs=[current_idx_state, mic_input, filter_dropdown],
            outputs=[current_idx_state, sentence_display, stats_display, tamang_display, existing_audio_player, mic_input, status_log]
        )

        # Save Only
        save_stay_btn.click(
            fn=lambda idx, aud, filt: save_and_advance(idx, aud, filt, advance_to_next=False),
            inputs=[current_idx_state, mic_input, filter_dropdown],
            outputs=[current_idx_state, sentence_display, stats_display, tamang_display, existing_audio_player, mic_input, status_log]
        )

        # Delete / Retake
        delete_btn.click(
            fn=delete_recording,
            inputs=[current_idx_state, filter_dropdown],
            outputs=[current_idx_state, sentence_display, stats_display, tamang_display, existing_audio_player, mic_input, status_log]
        )

        # Navigation
        prev_btn.click(
            fn=lambda idx, filt: navigate(idx, "prev", filt),
            inputs=[current_idx_state, filter_dropdown],
            outputs=[current_idx_state, sentence_display, stats_display, tamang_display, existing_audio_player, mic_input, status_log]
        )

        next_btn.click(
            fn=lambda idx, filt: navigate(idx, "next", filt),
            inputs=[current_idx_state, filter_dropdown],
            outputs=[current_idx_state, sentence_display, stats_display, tamang_display, existing_audio_player, mic_input, status_log]
        )

        next_unrec_btn.click(
            fn=lambda idx, filt: navigate(idx, "next_unrecorded", filt),
            inputs=[current_idx_state, filter_dropdown],
            outputs=[current_idx_state, sentence_display, stats_display, tamang_display, existing_audio_player, mic_input, status_log]
        )

        # Filter mode changed
        filter_dropdown.change(
            fn=lambda filt: navigate(0, "first", filt),
            inputs=[filter_dropdown],
            outputs=[current_idx_state, sentence_display, stats_display, tamang_display, existing_audio_player, mic_input, status_log]
        )

        # Jump to Index
        index_input.submit(
            fn=lambda num, filt: get_sentence_state(int(num) - 1, filt),
            inputs=[index_input, filter_dropdown],
            outputs=[current_idx_state, sentence_display, stats_display, tamang_display, existing_audio_player, mic_input, status_log]
        )

        # Jump to ID
        id_search_input.change(
            fn=jump_to_sentence_id,
            inputs=[id_search_input, filter_dropdown],
            outputs=[current_idx_state, sentence_display, stats_display, tamang_display, existing_audio_player, mic_input, status_log]
        )

        # Load initial state on page open
        demo.load(
            fn=lambda: get_sentence_state(0, "All"),
            outputs=[current_idx_state, sentence_display, stats_display, tamang_display, existing_audio_player, mic_input, status_log]
        )

    return demo, custom_css


if __name__ == "__main__":
    demo, css = build_app()
    port = int(os.environ.get("PORT", 7865))
    print(f"Starting Audio Recording Studio on http://127.0.0.1:{port}")
    demo.launch(
        server_name="127.0.0.1",
        server_port=port,
        theme=gr.themes.Soft(primary_hue="blue"),
        css=css,
        share=False
    )
