# NepTam Audio: Spoken Nepali Evaluation Corpus & Recording Studio

This directory contains the **Spoken Nepali Audio Corpus**, recording tools, and acoustic metadata for the **[NepTam Benchmark (LREC 2026)](https://github.com/DOAIxILPRL-KathmanduUniversity/NepTam-A-Nepali-Tamang-Parallel-Corpus-and-Baseline-Machine-Translation-Experiments)**.

---

## 📊 Dataset Overview

The audio files correspond to native spoken Nepali sentences from the **NepTam20k test split** (`test.csv`). Each clip is named by its corresponding `sentence_id` (e.g. `SO-333.mp3`).

| Metric | Value |
| :--- | :--- |
| **Total Recorded Sentences** | **1,388 clips** (out of 5,000 test sentences) |
| **Total Speech Duration** | **~65.4 minutes** (1.09 hours) |
| **Audio Format** | **MP3 mono @ 44.1 kHz, 192 kbps** |
| **Loudness Normalization** | **-20.0 dBFS RMS** (peak capped at -1.0 dBFS) |
| **Cleanup Pipeline** | DC offset removal, start/stop click trimming, 150 ms silence padding |

### Sentence Distribution (Recorded Subset)
- **Short**: 1,119 sentences
- **Medium**: 198 sentences
- **Long**: 42 sentences
- **Very Long**: 29 sentences

---

## 📁 Directory Structure

```text
audio/
├── README.md                  # Audio corpus documentation (this file)
├── .gitignore                 # Excludes caches, OS metadata, and temporary audio
├── app.py                     # Standalone Gradio recording & review studio
├── test.csv                   # Test set sentence index (matches NepTam20k_test.csv)
├── data/                      # 1,388 normalized MP3 audio files (<sentence_id>.mp3)
└── studio/                    # FastAPI Web Recording & DSP Studio
    ├── server.py              # Backend server with real-time DSP cleanup pipeline
    ├── recordings_meta.json   # Clip-level quality metadata (duration, levels, flags)
    └── static/                # Interactive web interface (record, review, dashboard)
        ├── dashboard.html
        ├── record.html
        ├── review.html
        ├── record.js
        ├── common.js
        └── styles.css
```

---

## 🚀 Running the Studio Application

Provides an interface for filtering sentences (Unrecorded / Recorded), playback, and browser microphone recording:
```bash
pip install gradio
python app.py
```
Open **`http://127.0.0.1:7865`** in your browser.

---

## 📋 Metadata Schema (`recordings_meta.json`)

Each recorded clip in `data/<sentence_id>.mp3` has quality metrics logged in `studio/recordings_meta.json`:

```json
{
  "SO-333": {
    "duration": 2.34,
    "speech_seconds": 1.34,
    "level_db": -27.7,
    "clipped_samples": 0,
    "chars_per_sec": 9.0,
    "flags": [],
    "recorded_at": "2026-10-04T01:56:17"
  }
}
```
