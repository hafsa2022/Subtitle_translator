# Subtitle Translator

A powerful GUI application that automatically extracts audio from videos, transcribes speech using OpenAI Whisper, translates subtitles to any language, and exports them in multiple formats. No complex setup required!

<img width="1290" height="864" alt="image" src="https://github.com/user-attachments/assets/9ff6b63d-067f-4578-a9ab-144f33b33b3e" />

## Features

- 🎬 **Video Processing**: Supports MP4, MKV, AVI, MOV, WMV, FLV, WebM, M4V, TS formats
- 🎙️ **AI Transcription**: Uses OpenAI Whisper for accurate speech-to-text
- 🌍 **Multi-language Translation**: Translates to 16+ languages including RTL support (Arabic, Hebrew, etc.)
- 📄 **Multiple Formats**: Export as SRT, VTT, ASS, or plain TXT
- 🎵 **Content Types**: Optimized for speech, lectures, music/songs, interviews, documentaries
- 🔥 **Video Burning**: Optionally burn subtitles directly into videos
- 📁 **Batch Processing**: Process entire folders of videos
- 🚀 **No Installation Required**: Automatic ffmpeg download, no system dependencies

## Requirements

**Python 3.8+** and these packages (installed automatically):

```bash
pip install openai-whisper deep-translator imageio-ffmpeg
```

> **Note**: `imageio-ffmpeg` automatically downloads ffmpeg binaries - no manual installation needed!

## Installation

1. Clone or download this repository
2. Install dependencies:
   ```bash
   pip install openai-whisper deep-translator imageio-ffmpeg
   ```
3. Run the application:
   ```bash
   python Subtitle_translator.py
   ```

## Usage

### Basic Workflow

1. **Launch the app**: Run `python Subtitle_translator.py`
2. **Select Input**: Choose a single video file or a folder containing multiple videos
3. **Choose Output**: Select where to save subtitle files (or use "Same folder as video")
4. **Configure Options**:
   - **Target Language**: Choose translation language (or "none" for no translation)
   - **Source Language**: Auto-detect or specify source language
   - **Whisper Model**: Select accuracy/speed trade-off
   - **Content Type**: Optimize for speech, music, interviews, etc.
   - **Formats**: Choose subtitle formats to generate
5. **Optional**: Enable "Burn into Video" to create subtitled video files
6. **Start**: Click "▶ Start Translation" and monitor progress in the log

### Whisper Models

| Model | Size | Speed | Accuracy | Use Case |
|-------|------|-------|----------|----------|
| Tiny | ~75 MB | ⚡ Fastest | Basic | Quick tests |
| Base | ~140 MB | ⚡ Fast | Good | General use |
| Small | ~460 MB | 🟡 Balanced | Better | Most videos |
| Medium | ~1.5 GB | 🟡 Slower | High | Important content |
| Large | ~3 GB | 🐌 Slowest | Best | Critical accuracy |

### Supported Languages

**Target Languages:**
- Arabic, Chinese (Simplified), Dutch, English, French, German, Hindi, Italian, Japanese, Korean, Polish, Portuguese, Russian, Spanish, Turkish, Ukrainian

**RTL Support:** Arabic, Hebrew, Persian, Urdu (with proper text shaping)

### Content Types

- **Speech/Lecture**: Standard transcription
- **Music/Song**: Optimized for sung lyrics with lower sensitivity thresholds
- **Interview**: Handles multiple speakers
- **Documentary**: General content with background audio

## Output Formats

- **SRT**: Standard subtitle format, widely supported
- **VTT**: WebVTT format for web players
- **ASS**: Advanced SubStation Alpha with styling (larger fonts for Arabic)
- **TXT**: Plain text transcript

## Advanced Features

### RTL Language Support

For Arabic and other right-to-left languages:
- Proper text shaping using `arabic-reshaper` and `python-bidi`
- Unicode RTL markers for correct display
- Larger fonts and right alignment in ASS format
- UTF-8 BOM encoding for Windows compatibility

### Video Burning

When enabled, creates a new video file with subtitles burned in:
- Yellow Arial text, 24pt, bold
- Black outline and shadow for readability
- Positioned at bottom with margins
- Re-encodes video using H.264 (high quality, fast preset)

### Batch Processing

Select a folder to process all supported video files automatically. Each video gets its own set of subtitle files.

## Troubleshooting

### Common Issues

**"Audio extraction failed"**
- Ensure video file has an audio track
- Try a different video format
- Check file permissions

**"Model download failed"**
- Check internet connection
- Try a smaller model first
- The app will retry automatically

**"Translation failed"**
- Google Translate rate limits - wait a few minutes
- Check internet connection
- Some segments may keep original text

**Slow processing**
- Use smaller Whisper models for faster results
- GPU acceleration requires CUDA (not included)

### Performance Tips

- **CPU-only**: Use "base" or "small" models
- **GPU**: Install CUDA and use larger models
- **Music**: Set content type to "Music/Song" and specify source language
- **Long videos**: Process in segments if needed

## Technical Details

### Dependencies

- **openai-whisper**: AI transcription model
- **deep-translator**: Google Translate API wrapper
- **imageio-ffmpeg**: Automatic ffmpeg binary management
- **tkinter**: GUI framework (built-in Python)
- **Optional**: arabic-reshaper, python-bidi (for RTL support)

### System Requirements

- **OS**: Windows, macOS, Linux
- **Python**: 3.8 or higher
- **RAM**: 4GB minimum, 8GB+ recommended
- **Storage**: 2GB+ free space for models
- **Internet**: Required for model downloads and translations

### File Structure

```
Subtitle_translator.py  # Main application
README.md              # This file
```

## License

This project is open source. Check the code for specific licensing of included libraries.

## Changelog

### v1.0
- Initial release
- Full Whisper integration
- Multi-language translation
- Multiple subtitle formats
- Video burning capability
- Batch processing
- RTL language support</content>
