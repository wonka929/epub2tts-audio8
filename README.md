# epub2tts-audio8

epub2tts-audio8 is a free and open source Python app to easily create a full-featured audiobook from an epub or text file using realistic text-to-speech by Audio8 TTS. CUDA compatible GPU is recommended, and Apple Silicon is also supported.

## Features

- [x] Creates standard format M4B audiobook file
- [x] Automatic chapter break detection
- [x] Embeds cover art if specified
- [x] Resumes where it left off if interrupted
- [x] Uses Audio8 TTS for high-quality, natural-sounding speech
- [x] Supports paragraph-level processing (no sentence splitting needed)
- [x] NOTE: epub file must be DRM-free

## Usage

<details>
<summary>Usage instructions</summary>

*NOTE:* If you want to specify where NLTK tokenizer will be stored (about 50mb), use an environment variable: `export NLTK_DATA="your/path/to/nltk_data"`

### OPTIONAL - activate the virtual environment if using
1. `source .venv/bin/activate`

### FIRST - extract epub contents to text and cover image to png:
1. `python epub2tt_audio8.py mybook.epub`
2. **edit mybook.txt**, replacing `# Part 1` etc with desired chapter names, and removing front matter like table of contents and anything else you do not want read. **Note:** First two lines can be Title: and Author: to use that in audiobook metadata.

### Read text to audiobook:

* `python epub2tt_audio8.py mybook.txt --cover mybook.png`
* Optional voice cloning with a reference clip (transcript is auto-generated if omitted):
  `python epub2tt_audio8.py mybook.txt --voice sample.wav --cover mybook.png`
* To supply the transcript yourself: `python epub2tt_audio8.py mybook.txt --voice sample.wav --voice-text "the exact words spoken" --cover mybook.png`
* Audio8 auto-detects the language of the text, so no language flag is required.

### All options
* `-h, --help` - show this help message and exit
* `--voice <path>` - Optional reference audio file used by Audio8 for zero-shot voice cloning
* `--voice-text <transcript>` - Transcript of the reference audio (inline text or a path to a .txt file). Required for cloning; if omitted, the app tries to transcribe it automatically with faster-whisper, then prompts you
* `--reference-seconds <n>` - Trim the reference voice clip to the first `n` seconds before cloning (default: 30). Audio8 only fits short references in its context; the transcript must match the trimmed segment
* `--transcribe-model <name>` - faster-whisper model used for auto-transcription (default: small). Sizes: tiny, base, small, medium, large-v3
* `--speaker <path>` - Deprecated alias for `--voice`
* `--language <language>` - Accepted for compatibility; Audio8 auto-detects the language from the text (default: en)
* `--model_path <path>` - Deprecated and ignored; Audio8 downloads the pretrained model automatically
* `--cover image.[jpg|png]` - Image to use for cover
* `--notitles` - Do not read chapter titles when creating audiobook


### Deactivate virtual environment
`deactivate`
</details>

## Reporting bugs

<details>
<summary>How to report bugs/issues</summary>

Thank you in advance for reporting any bugs/issues you encounter! If you are having issues, first please search existing issues to see if anyone else has run into something similar previously.

If you've found something new, please open an issue and be sure to include:
1. The full command you executed
2. The platform (Linux, Windows, OSX)
3. Your Python version if not using Docker

</details>

## Release notes

<details>
<summary>Release notes</summary>

* 20260401: Initial release with Chatterbox support
* 20260731: Switched TTS backend from Chatterbox to Audio8 TTS Preview 0.6B

</details>

## Install

Required Python version is 3.11.

*NOTE:* If you want to specify where NLTK tokenizer will be stored (about 50mb), use an environment variable: `export NLTK_DATA="your/path/to/nltk_data"`

<details>
<summary>MAC INSTALLATION</summary>

This installation requires Python 3.11 and [Homebrew](https://brew.sh/).

```bash
# Install dependencies
brew install mecab espeak pyenv ffmpeg

# Install epub2tts-audio8
git clone https://github.com/wonka929/epub2tts-audio8
cd epub2tts-audio8
pyenv install 3.11
pyenv local 3.11

# Create and activate virtual environment
python -m venv .venv && source .venv/bin/activate

# Install with uv (recommended)
pip install uv
uv pip install wheel
uv pip install .
uv pip install flash-attn --no-build-isolation

# Or install with pip
# pip install wheel
# pip install .
# pip install flash-attn --no-build-isolation
```
</details>

<details>
<summary>LINUX INSTALLATION</summary>

These instructions are for Ubuntu 22.04+ (20.04 showed some dependency issues), but should work (with appropriate package installer mods) for just about any distro. Ensure you have `ffmpeg` installed before use.

```bash
# Install dependencies
sudo apt install espeak-ng ffmpeg python3-venv

# Clone the repo
git clone https://github.com/wonka929/epub2tts-audio8
cd epub2tts-audio8

# Create and activate virtual environment
python3 -m venv .venv && source .venv/bin/activate

# Install with uv (recommended)
pip install uv
uv pip install wheel
uv pip install .
uv pip install flash-attn --no-build-isolation


# Or install with pip
# pip install wheel
# pip install .
# pip install flash-attn --no-build-isolation

```
</details>

<details>
<summary>WINDOWS INSTALLATION</summary>

Running epub2tts-audio8 in WSL2 with Ubuntu 22 is the easiest approach.

Follow the Linux installation instructions in WSL2.

</details>

## Updating

<details>
<summary>UPDATING YOUR INSTALLATION</summary>

1. cd to repo directory
2. `git pull`
3. Activate virtual environment you installed epub2tts-audio8 in if you installed in a virtual environment using "source .venv/bin/activate"
4. `uv pip install . --upgrade` (or `pip install . --upgrade` if not using uv)
</details>

## Requirements

- Python 3.11+
- CUDA-compatible GPU (NVIDIA) or Apple Silicon for best performance
- CPU-only mode is supported but will be significantly slower
- ffmpeg (for M4B creation)

## Audio8 Model

This application uses Audio8 TTS for text-to-speech synthesis.

**What's expected:**
- `transformers>=4.57.0` (installable via `pip install "transformers>=4.57.0,<5"`).
- On first use, the pretrained model is downloaded automatically from Hugging Face (`Audio8/Audio8-TTS-Preview-0.6b`, ~2.6GB).
- For voice cloning, pass a reference clip with `--voice path/to/reference.wav` and its exact transcript with `--voice-text "transcript"`.

Supported languages (Preview): Cantonese, Chinese, Dutch, English, French, German, Italian, Japanese, Korean, Polish, Spanish.

Refer to the Audio8 TTS README for supported languages and hardware recommendations.

## Voice cloning notes

- Reference clips are trimmed to `--reference-seconds` (default 30s) because the model's context only fits short references. The transcript must match the trimmed audio.
- If you don't supply `--voice-text`, the app transcribes the reference automatically with faster-whisper (first run downloads the whisper model, ~460MB for `small`). You can still pass the transcript yourself for better accuracy.
- Reference audio in formats soundfile can't read (e.g. `.opus`) is converted to WAV automatically via ffmpeg.
- Long, noisy, or incorrectly transcribed references reduce speaker similarity.

## Troubleshooting

<details>
<summary>Older GPUs (e.g. GTX 980M / Maxwell): "no kernel image is available"</summary>

Newer PyTorch wheels (CUDA 13.x) dropped support for Maxwell/Pascal GPUs. If you hit `CUDA error: no kernel image is available for execution on the device`, install a CUDA 12.4 build of PyTorch instead:

```bash
pip install torch==2.6.0+cu124 torchaudio==2.6.0+cu124 --index-url https://download.pytorch.org/whl/cu124
```

</details>


## Author

**Christopher Aedo and Francesco Manghi**

- Website: [aedo.dev](https://aedo.dev)
- GitHub: [@aedocw](https://github.com/aedocw)
- GitHub: [@wonka929](https://github.com/wonka929)

## Contributing

Contributions, issues and feature requests are welcome!

## Show your support

Give a star if this project helped you!

## License

This project uses Audio8 TTS, which is released under its own license terms. Please review the [Audio8 TTS project documentation and license](https://github.com/Audio8-AI/Audio8_TTS) for details.
