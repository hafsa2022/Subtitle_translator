"""
Subtitle Translator - Tkinter GUI App
Extracts audio from video(s), transcribes with Whisper, translates, and exports subtitles.

Requirements (pip only — NO system install needed):
    pip install openai-whisper deep-translator imageio-ffmpeg

    • imageio-ffmpeg  →  downloads ffmpeg automatically the first time (no sudo/admin needed)
    • openai-whisper  →  AI transcription (also auto-downloads model weights on first use)
    • deep-translator →  Google Translate bridge (free, no API key)
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import os
import sys
import queue
import json
from pathlib import Path

# ─────────────────────────────────────────────
# LANGUAGE & FORMAT OPTIONS
# ─────────────────────────────────────────────
LANGUAGES = {
    "Arabic": "ar",
    "Chinese (Simplified)": "zh-CN",
    "Dutch": "nl",
    "English": "en",
    "French": "fr",
    "German": "de",
    "Hindi": "hi",
    "Italian": "it",
    "Japanese": "ja",
    "Korean": "ko",
    "Polish": "pl",
    "Portuguese": "pt",
    "Russian": "ru",
    "Spanish": "es",
    "Turkish": "tr",
    "Ukrainian": "uk",
}

SUBTITLE_FORMATS = ["SRT", "VTT", "ASS", "TXT"]
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large"]
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts"}


# ─────────────────────────────────────────────
# SUBTITLE FORMATTERS
# ─────────────────────────────────────────────
def format_time_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def format_time_vtt(seconds: float) -> str:
    return format_time_srt(seconds).replace(",", ".")


# ── RTL support ──────────────────────────────────────────────────────────
RTL_LANGS = {"ar", "he", "fa", "ur"}

def _prepare_text(text: str, lang_code: str) -> str:
    """Reshape Arabic letters and wrap with RTL markers if needed."""
    text = text.strip()
    if lang_code not in RTL_LANGS:
        return text
    # Try arabic-reshaper + python-bidi for proper letter joining
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        text = get_display(arabic_reshaper.reshape(text))
    except ImportError:
        pass  # works without — modern players handle it
    # Wrap with Unicode RTL marks so players know direction
    return "\u200f" + text + "\u200f"

def segments_to_srt(segments, lang_code: str = "") -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{format_time_srt(seg['start'])} --> {format_time_srt(seg['end'])}")
        lines.append(_prepare_text(seg["text"], lang_code))
        lines.append("")
    return "\n".join(lines)


def segments_to_vtt(segments, lang_code: str = "") -> str:
    is_rtl = lang_code in RTL_LANGS
    lines = ["WEBVTT", ""]
    for seg in segments:
        timing = f"{format_time_vtt(seg['start'])} --> {format_time_vtt(seg['end'])}"
        if is_rtl:
            timing += " align:right"
        lines.append(timing)
        lines.append(_prepare_text(seg["text"], lang_code))
        lines.append("")
    return "\n".join(lines)


def segments_to_ass(segments, lang_code: str = "") -> str:
    is_rtl = lang_code in RTL_LANGS
    # Arabic style: larger font, Arabic encoding (177), right-aligned (alignment=9)
    if is_rtl:
        style = "Style: Arabic,Arial,36,&H00FFFFFF,0,0,0,0,100,100,0,0,1,2,1,9,20,20,20,177"
    else:
        style = "Style: Default,Arial,32,&H00FFFFFF,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1"

    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        f"Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n{style}\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def ass_time(s):
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = s % 60
        return f"{h}:{m:02}:{sec:05.2f}"

    style_name = "Arabic" if is_rtl else "Default"
    events = []
    for seg in segments:
        start = ass_time(seg["start"])
        end   = ass_time(seg["end"])
        text  = _prepare_text(seg["text"], lang_code).replace("\n", "\\N")
        events.append(f"Dialogue: 0,{start},{end},{style_name},,0,0,0,,{text}")
    return header + "\n".join(events)


def segments_to_txt(segments, lang_code: str = "") -> str:
    return "\n".join(_prepare_text(seg["text"], lang_code) for seg in segments)


FORMAT_WRITERS = {
    "SRT": (segments_to_srt, ".srt"),
    "VTT": (segments_to_vtt, ".vtt"),
    "ASS": (segments_to_ass, ".ass"),
    "TXT": (segments_to_txt, ".txt"),
}


# ─────────────────────────────────────────────
# CORE PROCESSING
# ─────────────────────────────────────────────
def extract_audio(video_path: str, audio_path: str, log_fn):
    """Extract audio using imageio-ffmpeg (auto-downloads ffmpeg binary, no system install needed)."""
    import imageio_ffmpeg
    import subprocess
    log_fn(f"  → Extracting audio from: {os.path.basename(video_path)}")
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()  # downloads ffmpeg automatically on first use
    # Use explicit str() + normpath to handle spaces and Unicode on Windows
    video_path = str(Path(video_path).resolve())
    audio_path = str(Path(audio_path).resolve())
    cmd = [
        ffmpeg_exe,
        "-y",                    # overwrite output
        "-i", video_path,        # input video
        "-vn",                   # no video stream
        "-acodec", "pcm_s16le",  # WAV PCM 16-bit
        "-ar", "16000",          # 16 kHz (Whisper native rate)
        "-ac", "1",              # mono
        audio_path,
    ]
    log_fn(f"  → ffmpeg: {os.path.basename(ffmpeg_exe)}")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(
            f"Audio extraction failed (ffmpeg exit {result.returncode}):\n"
            f"{result.stderr[-1200:]}"
        )


def _download_whisper_model_with_retry(model_name: str, log_fn, max_retries: int = 5):
    """Download Whisper model with automatic retry on connection errors."""
    import whisper
    import whisper.utils
    import urllib.request
    import os

    # Whisper stores models in ~/.cache/whisper
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "whisper")
    os.makedirs(cache_dir, exist_ok=True)

    # Map model name → download URL (same as whisper internals)
    _MODELS = {
        "tiny":   "https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt",
        "base":   "https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt",
        "small":  "https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt",
        "medium": "https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt",
        "large":  "https://openaipublic.azureedge.net/main/whisper/models/e4b87e7e0bf463eb8e6956e646f1e277e901512310def2c24bf0e11bd3c28e9a/large-v2.pt",
    }

    url = _MODELS.get(model_name)
    if url is None:
        # Unknown model name — let whisper handle it normally
        import whisper
        return whisper.load_model(model_name)

    filename = os.path.basename(url.split("/")[-2]) + ".pt" if model_name == "large" else f"{model_name}.pt"
    # Use whisper's actual cache filename (sha256 prefix)
    dest = os.path.join(cache_dir, os.path.basename(url))

    if not os.path.exists(dest):
        for attempt in range(1, max_retries + 1):
            try:
                log_fn(f"  → Downloading Whisper '{model_name}' model (attempt {attempt}/{max_retries})…")
                log_fn(f"  ℹ  This runs in background — the UI stays responsive. Please wait.")
                tmp_dest = dest + ".part"
                downloaded = os.path.getsize(tmp_dest) if os.path.exists(tmp_dest) else 0

                req = urllib.request.Request(url)
                if downloaded > 0:
                    req.add_header("Range", f"bytes={downloaded}-")
                    log_fn(f"  → Resuming from {downloaded // (1024*1024)} MB…")

                with urllib.request.urlopen(req, timeout=120) as resp:
                    total = int(resp.headers.get("Content-Length", 0)) + downloaded
                    total_mb = total / (1024 * 1024)
                    mode = "ab" if downloaded > 0 else "wb"
                    chunk = 4 * 1024 * 1024  # 4 MB chunks for speed
                    last_logged_pct = -5      # log every 5%
                    with open(tmp_dest, mode) as f:
                        while True:
                            data = resp.read(chunk)
                            if not data:
                                break
                            f.write(data)
                            downloaded += len(data)
                            if total:
                                pct = int(downloaded / total * 100)
                                if pct >= last_logged_pct + 5:
                                    last_logged_pct = pct
                                    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                                    log_fn(f"  [{bar}] {pct}%  ({downloaded // (1024*1024):.0f}/{total_mb:.0f} MB)")

                os.rename(tmp_dest, dest)
                log_fn(f"  ✓ Model downloaded successfully.")
                break

            except Exception as e:
                log_fn(f"  ⚠ Download error (attempt {attempt}): {e}")
                if attempt == max_retries:
                    raise RuntimeError(
                        f"Failed to download Whisper model after {max_retries} attempts.\n"
                        f"Check your internet connection or try a smaller model (e.g. 'small' or 'medium')."
                    )
                import time
                wait = attempt * 5
                log_fn(f"  → Retrying in {wait}s…")
                time.sleep(wait)

    import whisper
    return whisper.load_model(model_name)


def transcribe_audio(audio_path: str, model_name: str, source_lang: str, log_fn,
                     content_type: str = "Speech / Lecture"):
    """Transcribe audio using Whisper — injects imageio-ffmpeg into PATH so Whisper finds it."""
    import whisper
    import wave, contextlib, time, imageio_ffmpeg

    # ── KEY FIX: Whisper internally calls ffmpeg by name from PATH.
    # We inject the imageio-ffmpeg binary directory into PATH so it is found
    # without any system-level ffmpeg installation.
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    ffmpeg_dir = str(Path(ffmpeg_exe).parent)
    if ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    # Whisper also looks for "ffmpeg" by that exact name; create a symlink/copy if needed
    ffmpeg_name = Path(ffmpeg_exe).name          # e.g. ffmpeg-win-x86_64-v7.1.exe
    ffmpeg_plain = Path(ffmpeg_dir) / "ffmpeg.exe"
    if not ffmpeg_plain.exists() and ffmpeg_name != "ffmpeg.exe":
        import shutil
        try:
            shutil.copy2(ffmpeg_exe, ffmpeg_plain)
            log_fn(f"  → Created ffmpeg.exe alias in {ffmpeg_dir}")
        except Exception as e:
            log_fn(f"  ⚠ Could not create ffmpeg alias: {e}")

    log_fn(f"  → Loading Whisper model '{model_name}'…")
    model = _download_whisper_model_with_retry(model_name, log_fn)

    # Get audio duration for progress display
    duration = 0.0
    try:
        with contextlib.closing(wave.open(audio_path, "r")) as wf:
            duration = wf.getnframes() / wf.getframerate()
    except Exception:
        pass

    total_str = f"{int(duration // 60)}m{int(duration % 60):02d}s" if duration else "?"
    log_fn(f"  → Transcribing… (audio duration: {total_str})")
    log_fn(f"  ⏳ Please wait — this can take several minutes on CPU…")

    start_time = time.time()
    lang_code = source_lang if source_lang != "auto" else None

    is_music = "Music" in content_type or "Song" in content_type
    if is_music:
        log_fn("  ℹ  Music mode: using lower thresholds for sung lyrics…")

    result = model.transcribe(
        audio_path,
        language=lang_code,
        verbose=False,
        condition_on_previous_text=True,
        temperature=0 if not is_music else (0, 0.2, 0.4),  # music needs fallback temps
        no_speech_threshold=0.3 if is_music else 0.4,       # more sensitive for music
        compression_ratio_threshold=2.8 if is_music else 2.4,
        word_timestamps=False,
        beam_size=5,
        best_of=5,
        fp16=False,
        initial_prompt=(
            "Transcribe sung lyrics accurately, including all words and filler sounds."
            if is_music else None
        ),
    )

    all_segments = result["segments"]
    total_segs = len(all_segments)
    elapsed_total = time.time() - start_time

    log_fn(f"  → Transcription complete in {int(elapsed_total // 60)}m{int(elapsed_total % 60):02d}s — {total_segs} segments")

    # Show per-segment progress replay
    last_logged_pct = -5
    for i, seg in enumerate(all_segments):
        pct = int((i + 1) / total_segs * 100) if total_segs else 100
        if pct >= last_logged_pct + 5 or i == total_segs - 1:
            last_logged_pct = pct
            filled = pct // 5
            bar = "█" * filled + "░" * (20 - filled)
            t_start = f"{int(seg['start'] // 60)}:{int(seg['start'] % 60):02d}"
            t_end   = f"{int(seg['end']   // 60)}:{int(seg['end']   % 60):02d}"
            snippet = seg["text"].strip()[:45]
            log_fn(f"  [{bar}] {pct:3d}%  [{t_start}→{t_end}]  {snippet}")

    log_fn(f"  ✓ {total_segs} segments transcribed.")
    return all_segments


def translate_segments(segments, target_lang_code: str, log_fn):
    """
    Translate with a sliding context window:
    - Sends a wider block of text to Google Translate so it understands the full sentence
    - Marks the TARGET segment with <<< >>> so we can extract just its translation
    - Falls back to direct translation if markers get lost
    """
    from deep_translator import GoogleTranslator
    import time, re

    total = len(segments)
    log_fn(f"  → Translating {total} segments to '{target_lang_code}'…")
    log_fn(f"  ℹ  Using context-window method for better accuracy…")

    translator     = GoogleTranslator(source="auto", target=target_lang_code)
    translated_texts = [""] * total
    last_logged_pct  = -5
    CONTEXT        = 3   # lines before+after for context
    START_MARK     = "<<<TARGET_START>>>"
    END_MARK       = "<<<TARGET_END>>>"

    for i, seg in enumerate(segments):
        # Build context window: lines before + marked target + lines after
        before = [segments[j]["text"].strip() for j in range(max(0, i - CONTEXT), i)]
        target = seg["text"].strip()
        after  = [segments[j]["text"].strip() for j in range(i + 1, min(total, i + CONTEXT + 1))]

        if not target:
            translated_texts[i] = target
        else:
            block = "\n".join(before + [f"{START_MARK}{target}{END_MARK}"] + after)

            result_block = block  # fallback
            for attempt in range(3):
                try:
                    result_block = translator.translate(block) or block
                    break
                except Exception as e:
                    if attempt == 2:
                        log_fn(f"  ⚠ seg {i}: {e} — keeping original")
                    else:
                        time.sleep(1.5)

            # Extract marked translation
            match = re.search(r"<<<TARGET_START>>>(.*?)<<<TARGET_END>>>",
                              result_block, re.DOTALL | re.IGNORECASE)
            if match:
                translated_texts[i] = match.group(1).strip()
            else:
                # Markers got eaten by translator — translate segment alone as fallback
                try:
                    translated_texts[i] = translator.translate(target) or target
                except Exception:
                    translated_texts[i] = target

        pct = int((i + 1) / total * 100)
        if pct >= last_logged_pct + 5 or i == total - 1:
            last_logged_pct = pct
            bar     = "█" * (pct // 5) + "░" * (20 - pct // 5)
            snippet = translated_texts[i][:42]
            log_fn(f"  [{bar}] {pct:3d}%  ({i+1}/{total})  │ {snippet}")

        # Small pause every 10 segments to avoid Google rate-limit
        if i % 10 == 9:
            time.sleep(0.5)

    translated = [{**seg, "text": translated_texts[k]} for k, seg in enumerate(segments)]
    log_fn(f"  ✓ Translation complete — {total} segments.")
    return translated


def process_video(video_path: str, output_dir: str, options: dict, log_fn):
    """Full pipeline for a single video."""
    import tempfile

    video_name = Path(video_path).stem
    # Use a safe ASCII-only temp filename to avoid Windows path/space issues
    safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in video_name)[:40]
    audio_tmp = os.path.join(tempfile.gettempdir(), f"_sub_{safe_name}.wav")

    try:
        # 1. Extract audio
        extract_audio(video_path, audio_tmp, log_fn)

        # Verify the audio file was actually created
        if not os.path.exists(audio_tmp) or os.path.getsize(audio_tmp) == 0:
            raise RuntimeError(
                f"Audio extraction produced no output.\n"
                f"Expected: {audio_tmp}\n"
                f"Check that the video file has an audio track."
            )
        log_fn(f"  → Audio extracted: {os.path.getsize(audio_tmp) // (1024*1024)} MB")

        # 2. Transcribe
        segments = transcribe_audio(
            audio_tmp,
            options["model"],
            options.get("source_lang", "auto"),
            log_fn,
            content_type=options.get("content_type", "Speech / Lecture"),
        )

        # 3. Translate (skip if target == source or "none")
        target_code = options["target_lang_code"]
        if target_code and target_code != "none":
            segments = translate_segments(segments, target_code, log_fn)

        # 4. Write subtitle file(s)
        lang_code = options.get("target_lang_code", "")
        is_rtl    = lang_code in RTL_LANGS
        srt_path_for_burn = None
        for fmt in options["formats"]:
            writer_fn, ext = FORMAT_WRITERS[fmt]
            out_filename = f"{video_name}{ext}"
            out_path = os.path.join(output_dir, out_filename)
            subtitle_content = writer_fn(segments, lang_code)
            # UTF-8 BOM helps Windows media players render Arabic correctly
            encoding = "utf-8-sig" if is_rtl else "utf-8"
            with open(out_path, "w", encoding=encoding) as f:
                f.write(subtitle_content)
            rtl_note = " ✦ RTL/Arabic" if is_rtl else ""
            log_fn(f"  ✓ Saved: {out_filename}{rtl_note}")
            if fmt == "SRT":
                srt_path_for_burn = out_path

        # 5. Burn subtitles into video (optional)
        if options.get("burn_video"):
            # Always need an SRT — generate a temp one if user didn't select SRT format
            if srt_path_for_burn is None:
                import tempfile
                srt_tmp = os.path.join(tempfile.gettempdir(), f"_sub_{safe_name}.srt")
                with open(srt_tmp, "w", encoding="utf-8") as f:
                    f.write(segments_to_srt(segments))
                srt_path_for_burn = srt_tmp
            video_ext = Path(video_path).suffix
            burned_filename = f"{video_name}_subtitled{video_ext}"
            burned_path = os.path.join(output_dir, burned_filename)
            burn_subtitles_into_video(video_path, srt_path_for_burn, burned_path, log_fn)

    finally:
        if os.path.exists(audio_tmp):
            os.remove(audio_tmp)


def burn_subtitles_into_video(video_path: str, srt_path: str, output_path: str, log_fn):
    """Burn SRT subtitles into video using ffmpeg — Netflix style (yellow, bold, bottom)."""
    import imageio_ffmpeg, subprocess

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    # Escape paths for ffmpeg subtitles filter (Windows backslashes → forward, colons escaped)
    srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")

    # Netflix-style subtitle filter:
    # - FontName: Arial  • FontSize: 24  • Bold: yes
    # - PrimaryColour: yellow (&H0000FFFF in ASS ABGR hex)
    # - Outline: 2px black  • Shadow: 1  • MarginV: 40px from bottom
    sub_filter = (
        f"subtitles='{srt_escaped}':"
        f"force_style='FontName=Arial,FontSize=24,Bold=1,"
        f"PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,"
        f"Outline=2,Shadow=1,Alignment=2,MarginV=40'"
    )

    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", str(Path(video_path).resolve()),
        "-vf", sub_filter,
        "-c:v", "libx264",   # re-encode video with burned subs
        "-crf", "18",        # high quality (0=lossless, 51=worst)
        "-preset", "fast",   # encoding speed vs compression
        "-c:a", "copy",      # copy audio stream as-is
        str(Path(output_path).resolve()),
    ]

    log_fn(f"  → Burning subtitles into video (this may take a while)…")
    log_fn(f"  → Output: {os.path.basename(output_path)}")

    process = subprocess.Popen(
        cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace"
    )

    # Parse ffmpeg stderr for time= progress
    duration_sec = 0.0
    last_logged_pct = -5
    for line in process.stderr:
        line = line.strip()
        # Extract total duration once
        if "Duration:" in line and duration_sec == 0:
            try:
                t = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = t.split(":")
                duration_sec = int(h)*3600 + int(m)*60 + float(s)
            except Exception:
                pass
        # Extract current time= progress
        if "time=" in line and duration_sec > 0:
            try:
                t = line.split("time=")[1].split(" ")[0].strip()
                h, m, s = t.split(":")
                current = int(h)*3600 + int(m)*60 + float(s)
                pct = min(int(current / duration_sec * 100), 100)
                if pct >= last_logged_pct + 5:
                    last_logged_pct = pct
                    filled = pct // 5
                    bar = "█" * filled + "░" * (20 - filled)
                    cur_str  = f"{int(current//60)}:{int(current%60):02d}"
                    tot_str  = f"{int(duration_sec//60)}:{int(duration_sec%60):02d}"
                    log_fn(f"  [{bar}] {pct:3d}%  [{cur_str}/{tot_str}]")
            except Exception:
                pass

    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg burn failed (exit {process.returncode}). Check your video file.")
    log_fn(f"  ✓ Video with burned subtitles saved: {os.path.basename(output_path)}")


# ─────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────
class SubtitleTranslatorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🎬 Subtitle Translator")
        self.resizable(True, True)
        self.configure(bg="#1e1e2e")
        self.minsize(860, 420)
        self._log_queue = queue.Queue()
        self._build_ui()
        self._poll_log()
        # Center window on screen
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ── UI Construction ──────────────────────
    def _build_ui(self):
        PAD = {"padx": 10, "pady": 4}
        BG = "#1e1e2e"
        FG = "#cdd6f4"
        ACCENT = "#89b4fa"
        ENTRY_BG = "#313244"
        FONT = ("Segoe UI", 10)
        FONT_BOLD = ("Segoe UI", 10, "bold")
        FONT_SM   = ("Segoe UI", 8)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame",       background=BG)
        style.configure("TLabel",       background=BG, foreground=FG,      font=FONT)
        style.configure("TLabelframe",  background=BG, foreground=ACCENT,  font=FONT_BOLD)
        style.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=FONT_BOLD)
        style.configure("TCombobox",    fieldbackground=ENTRY_BG, background=ENTRY_BG,
                        foreground=FG,  selectbackground=ENTRY_BG, font=FONT)
        style.configure("TCheckbutton", background=BG, foreground=FG, font=FONT)
        style.configure("TButton",      background=ACCENT, foreground="#1e1e2e", font=FONT_BOLD, padding=5)
        style.map("TButton",            background=[("active", "#74c7ec")])
        style.configure("TRadiobutton", background=BG, foreground=FG, font=FONT)
        style.configure("Vertical.TScrollbar", background=ENTRY_BG, troughcolor=BG, arrowcolor=FG)

        # ── Outer scrollable container ────────────────────────────────────────
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        vsb    = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        # Inner frame that holds all widgets
        inner = ttk.Frame(canvas, padding=0)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_resize(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(inner_id, width=canvas.winfo_width())
        inner.bind("<Configure>", _on_inner_resize)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(inner_id, width=e.width))

        # Mouse-wheel scrolling (Windows + Linux)
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>",   lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>",   lambda e: canvas.yview_scroll( 1, "units"))

        main = ttk.Frame(inner, padding=14)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=1)

        # ── Row 0: Input + Output side by side ───────────────────────────────
        top_frame = ttk.Frame(main)
        top_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        top_frame.columnconfigure(0, weight=1)
        top_frame.columnconfigure(1, weight=0)

        # Input
        inp_frame = ttk.LabelFrame(top_frame, text=" 📂  Input ", padding=8)
        inp_frame.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        inp_frame.columnconfigure(1, weight=1)

        self._mode = tk.StringVar(value="single")
        ttk.Radiobutton(inp_frame, text="Single video", variable=self._mode,
                        value="single", command=self._on_mode_change).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(inp_frame, text="Folder (batch)", variable=self._mode,
                        value="folder", command=self._on_mode_change).grid(row=0, column=1, sticky="w", padx=16)

        self._input_var = tk.StringVar()
        self._input_entry = ttk.Entry(inp_frame, textvariable=self._input_var, width=55, font=FONT)
        self._input_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._browse_btn = ttk.Button(inp_frame, text="Browse…", command=self._browse_input)
        self._browse_btn.grid(row=1, column=2, padx=(6, 0))

        # Output (compact, right of input)
        out_frame = ttk.LabelFrame(top_frame, text=" 💾  Output ", padding=8)
        out_frame.grid(row=0, column=1, sticky="nsew")
        out_frame.columnconfigure(0, weight=1)

        self._output_var = tk.StringVar()
        self._out_entry = ttk.Entry(out_frame, textvariable=self._output_var, width=28, font=FONT)
        self._out_entry.grid(row=0, column=0, sticky="ew")
        self._out_browse_btn = ttk.Button(out_frame, text="Browse…", command=self._browse_output)
        self._out_browse_btn.grid(row=0, column=1, padx=(4, 0))

        self._same_dir_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(out_frame, text="Same folder as video", variable=self._same_dir_var,
                        command=self._toggle_output).grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self._toggle_output()

        # ── Row 1: Language | Model | Format (3 columns) ─────────────────────
        mid_frame = ttk.Frame(main)
        mid_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=4)
        mid_frame.columnconfigure(0, weight=2)
        mid_frame.columnconfigure(1, weight=2)
        mid_frame.columnconfigure(2, weight=1)

        # Language
        lang_frame = ttk.LabelFrame(mid_frame, text=" 🌍  Language ", padding=8)
        lang_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        ttk.Label(lang_frame, text="Target:").grid(row=0, column=0, sticky="w")
        self._target_lang = tk.StringVar(value="French")
        lang_cb = ttk.Combobox(lang_frame, textvariable=self._target_lang,
                               values=list(LANGUAGES.keys()), state="readonly", width=20)
        lang_cb.grid(row=0, column=1, sticky="w", padx=(6, 0))
        lang_cb.bind("<<ComboboxSelected>>", self._on_lang_change)

        self._rtl_badge = ttk.Label(lang_frame, text="", font=FONT_SM, foreground="#f9e2af")
        self._rtl_badge.grid(row=0, column=2, padx=(6, 0))

        ttk.Label(lang_frame, text="Source:").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self._source_lang = tk.StringVar(value="Auto-detect")
        src_cb = ttk.Combobox(lang_frame, textvariable=self._source_lang,
                              values=["Auto-detect"] + list(LANGUAGES.keys()), state="readonly", width=20)
        src_cb.grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(5, 0))

        ttk.Label(lang_frame, text="Content:").grid(row=2, column=0, sticky="w", pady=(5, 0))
        self._content_type = tk.StringVar(value="Speech / Lecture")
        content_cb = ttk.Combobox(lang_frame, textvariable=self._content_type,
                                  values=["Speech / Lecture", "Music / Song", "Interview", "Documentary"],
                                  state="readonly", width=20)
        content_cb.grid(row=2, column=1, sticky="w", padx=(6, 0), pady=(5, 0))
        self._content_hint = ttk.Label(lang_frame, text="", font=FONT_SM, foreground="#f38ba8")
        self._content_hint.grid(row=3, column=0, columnspan=3, sticky="w", pady=(2, 0))
        content_cb.bind("<<ComboboxSelected>>", self._on_content_change)

        # Model
        model_frame = ttk.LabelFrame(mid_frame, text=" 🤖  Whisper Model ", padding=8)
        model_frame.grid(row=0, column=1, sticky="nsew", padx=(0, 5))

        self._model = tk.StringVar(value="base")
        model_cb = ttk.Combobox(model_frame, textvariable=self._model,
                                values=WHISPER_MODELS, state="readonly", width=12)
        model_cb.grid(row=0, column=0, sticky="w")
        model_cb.bind("<<ComboboxSelected>>", self._on_model_change)
        self._model_hint = ttk.Label(model_frame, text="~140 MB · fast",
                                     font=FONT_SM, foreground="#f9e2af")
        self._model_hint.grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(model_frame, text="larger = more accurate", font=FONT_SM,
                  foreground="#6c7086").grid(row=2, column=0, sticky="w")

        # Format
        fmt_frame = ttk.LabelFrame(mid_frame, text=" 📄  Format ", padding=8)
        fmt_frame.grid(row=0, column=2, sticky="nsew")

        self._fmt_vars = {}
        for i, fmt in enumerate(SUBTITLE_FORMATS):
            var = tk.BooleanVar(value=(fmt == "SRT"))
            self._fmt_vars[fmt] = var
            ttk.Checkbutton(fmt_frame, text=fmt, variable=var).grid(
                row=i, column=0, sticky="w")

        # ── Burn video section ──
        burn_frame = ttk.LabelFrame(main, text=" 🎬  Burn into Video ", padding=10)
        burn_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4,2))

        self._burn_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            burn_frame,
            text="Generate video with subtitles burned in  (Netflix style — yellow, bold)",
            variable=self._burn_var,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            burn_frame,
            text="⚠ Re-encodes the video — takes extra time proportional to video length",
            font=("Segoe UI", 8), foreground="#f38ba8",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        # ── Run button ──
        self._run_btn = ttk.Button(main, text="▶  Start Translation", command=self._start)
        self._run_btn.grid(row=3, column=0, columnspan=2, pady=(6, 2), sticky="ew")

        self._progress = ttk.Progressbar(main, mode="indeterminate")
        self._progress.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 2))

        # ── Log ──
        log_frame = ttk.LabelFrame(main, text=" 📋  Log ", padding=4)
        log_frame.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(0, 4))
        main.rowconfigure(5, weight=1)

        self._log = scrolledtext.ScrolledText(
            log_frame, height=10, width=90, font=("Consolas", 9),
            bg="#181825", fg="#a6e3a1", insertbackground=FG, state="disabled", wrap="word")
        self._log.pack(fill="both", expand=True)

    # ── UI helpers ───────────────────────────
    _MODEL_INFO = {
        "tiny":   ("~75 MB · fastest",  "#a6e3a1"),
        "base":   ("~140 MB · fast",    "#f9e2af"),
        "small":  ("~460 MB · balanced","#f9e2af"),
        "medium": ("~1.5 GB · accurate","#f9e2af"),
        "large":  ("~3 GB · best · ⚠ slow download", "#f38ba8"),
    }

    def _on_model_change(self, _event=None):
        m = self._model.get()
        text, color = self._MODEL_INFO.get(m, ("", "#f9e2af"))
        self._model_hint.configure(text=text, foreground=color)

    def _on_lang_change(self, _event=None):
        lang = LANGUAGES.get(self._target_lang.get(), "")
        if lang in RTL_LANGS:
            self._rtl_badge.configure(text="↰ RTL", foreground="#f9e2af")
        else:
            self._rtl_badge.configure(text="")

    def _on_content_change(self, _event=None):
        ct = self._content_type.get()
        if ct == "Music / Song":
            self._content_hint.configure(
                text="⚠ Songs: use 'small' or 'medium' model + set Source language for best results",
                foreground="#f38ba8")
        else:
            self._content_hint.configure(text="")

    def _on_mode_change(self):
        pass

    def _browse_input(self):
        if self._mode.get() == "single":
            path = filedialog.askopenfilename(
                title="Select video file",
                filetypes=[("Video files", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.m4v *.ts"),
                           ("All files", "*.*")])
        else:
            path = filedialog.askdirectory(title="Select folder with videos")
        if path:
            self._input_var.set(path)
            if self._same_dir_var.get():
                self._output_var.set(os.path.dirname(path) if os.path.isfile(path) else path)

    def _browse_output(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self._output_var.set(path)

    def _toggle_output(self):
        state = "disabled" if self._same_dir_var.get() else "normal"
        try:
            self._out_entry.configure(state=state)
            self._out_browse_btn.configure(state=state)
        except AttributeError:
            pass  # widgets not yet created

    def _log_msg(self, msg: str):
        self._log_queue.put(msg)

    def _poll_log(self):
        while not self._log_queue.empty():
            msg = self._log_queue.get_nowait()
            self._log.configure(state="normal")
            self._log.insert("end", msg + "\n")
            self._log.see("end")
            self._log.configure(state="disabled")
        self.after(100, self._poll_log)

    # ── Validation ───────────────────────────
    def _validate(self):
        if not self._input_var.get():
            messagebox.showerror("Missing input", "Please select a video file or folder.")
            return False
        formats = [f for f, v in self._fmt_vars.items() if v.get()]
        if not formats:
            messagebox.showerror("No format", "Please select at least one output format.")
            return False
        return True

    # ── Start processing ─────────────────────
    def _start(self):
        if not self._validate():
            return

        # Collect options
        target_name = self._target_lang.get()
        source_name = self._source_lang.get()
        options = {
            "target_lang_code": LANGUAGES.get(target_name, "fr"),
            "source_lang": None if source_name == "Auto-detect" else LANGUAGES.get(source_name),
            "model": self._model.get(),
            "formats": [f for f, v in self._fmt_vars.items() if v.get()],
            "burn_video": self._burn_var.get(),
            "content_type": self._content_type.get(),
        }

        input_path = self._input_var.get()
        if self._same_dir_var.get():
            output_dir = os.path.dirname(input_path) if os.path.isfile(input_path) else input_path
        else:
            output_dir = self._output_var.get() or os.path.dirname(input_path)

        # Gather video list
        if self._mode.get() == "single":
            videos = [input_path]
        else:
            videos = [
                os.path.join(input_path, f)
                for f in os.listdir(input_path)
                if Path(f).suffix.lower() in VIDEO_EXTENSIONS
            ]
            if not videos:
                messagebox.showwarning("No videos", "No supported video files found in the folder.")
                return

        os.makedirs(output_dir, exist_ok=True)

        self._run_btn.configure(state="disabled")
        self._progress.start(10)
        self._log_msg(f"{'='*60}")
        burn_str = "  +  🎬 Burn into video" if options["burn_video"] else ""
        self._log_msg(f"Starting: {len(videos)} video(s) → {', '.join(options['formats'])}{burn_str}")
        self._log_msg(f"Target language: {target_name}  |  Model: {options['model']}")
        self._log_msg(f"Output folder: {output_dir}")
        self._log_msg(f"{'='*60}")

        threading.Thread(
            target=self._worker,
            args=(videos, output_dir, options),
            daemon=True,
        ).start()

    def _worker(self, videos, output_dir, options):
        errors = []
        for idx, video in enumerate(videos, 1):
            self._log_msg(f"\n[{idx}/{len(videos)}] {os.path.basename(video)}")
            try:
                process_video(video, output_dir, options, self._log_msg)
            except Exception as e:
                self._log_msg(f"  ✗ ERROR: {e}")
                errors.append((video, str(e)))

        self._log_msg(f"\n{'='*60}")
        if errors:
            self._log_msg(f"Done with {len(errors)} error(s):")
            for v, e in errors:
                self._log_msg(f"  • {os.path.basename(v)}: {e}")
        else:
            self._log_msg(f"✅  All done! {len(videos)} video(s) processed successfully.")
        self._log_msg(f"{'='*60}")

        self.after(0, self._on_done)

    def _on_done(self):
        self._progress.stop()
        self._run_btn.configure(state="normal")
        messagebox.showinfo("Done", "Subtitle translation complete! Check the log for details.")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    app = SubtitleTranslatorApp()
    app.mainloop()