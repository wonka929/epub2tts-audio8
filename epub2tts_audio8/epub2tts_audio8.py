import os
import sys
import argparse
import time
import re
import subprocess
import torch
import warnings

from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub
from lxml import etree
from mutagen import mp4
import nltk
from nltk.tokenize import sent_tokenize
from PIL import Image
from pydub import AudioSegment
import zipfile

# Audio writing stays local; Audio8 imports are loaded lazily in `read_book`
import soundfile as sf

warnings.filterwarnings("ignore")

namespaces = {
   "calibre":"http://calibre.kovidgoyal.net/2009/metadata",
   "dc":"http://purl.org/dc/elements/1.1/",
   "dcterms":"http://purl.org/dc/terms/",
   "opf":"http://www.idpf.org/2007/opf",
   "u":"urn:oasis:names:tc:opendocument:xmlns:container",
   "xsi":"http://www.w3.org/2001/XMLSchema-instance",
}

warnings.filterwarnings("ignore", module="ebooklib.epub")

def ensure_punkt():
    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        nltk.download("punkt")
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt_tab")

def format_time_adaptive(seconds):
    """Format time in adaptive format, showing only relevant units."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"

def chap2text_epub(chap, item_id=None, toc=None):
    """
    Extract chapter title and paragraphs from an EPUB chapter.

    Args:
        chap: The chapter content (HTML).
        item_id: The ID of the item in the EPUB spine (for fallback naming).
        toc: The EPUB's table of contents (for fallback title extraction).

    Returns:
        tuple: (chapter_title_text, paragraphs)
    """
    blacklist = [
        "[document]",
        "noscript",
        "header",
        "html",
        "meta",
        "head",
        "input",
        "script",
    ]
    paragraphs = []
    soup = BeautifulSoup(chap, "html.parser")

    # Step 1: Try to find chapter title in heading tags (<h1>, <h2>, <h3>)
    heading_tags = ['h1', 'h2', 'h3']
    chapter_title_text = None
    for tag in heading_tags:
        heading = soup.find(tag)
        if heading and heading.text.strip():
            chapter_title_text = heading.text.strip()
            print(f"Found title in <{tag}>: '{chapter_title_text}'")
            break

    # Step 2: If no heading found, try elements with common class names
    if not chapter_title_text:
        common_classes = ['chapter', 'chapter-title', 'title', 'heading']
        for class_name in common_classes:
            element = soup.find(class_=class_name)
            if element and element.text.strip():
                chapter_title_text = element.text.strip()
                print(f"Found title in class '{class_name}': '{chapter_title_text}'")
                break

    # Step 3: Fallback to TOC if provided
    if not chapter_title_text and toc and item_id:
        for toc_item in toc:
            if toc_item.href.split('#')[0] == item_id:
                chapter_title_text = toc_item.title
                print(f"Found title in TOC for item '{item_id}': '{chapter_title_text}'")
                break

    # Step 4: Fallback to item ID or generic name
    if not chapter_title_text:
        chapter_title_text = item_id.replace('.xhtml', '').replace('_', ' ').title() if item_id else None
        print(f"No title found, using fallback: '{chapter_title_text}'")

    # Remove footnotes (links with only numbers)
    for a in soup.findAll("a", href=True):
        if not any(char.isalpha() for char in a.text):
            a.extract()

    # Remove superscript numbers (e.g., footnote markers)
    for sup in soup.findAll("sup"):
        if sup.text.isdigit():
            sup.extract()

    # Extract paragraphs
    chapter_paragraphs = soup.find_all("p")
    if not chapter_paragraphs:
        print(f"No <p> tags found in '{chapter_title_text or item_id}'. Trying <div>.")
        chapter_paragraphs = soup.find_all("div")

    for p in chapter_paragraphs:
        paragraph_text = "".join(p.strings).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)

    return chapter_title_text, paragraphs

def get_epub_cover(epub_path):
    try:
        with zipfile.ZipFile(epub_path) as z:
            t = etree.fromstring(z.read("META-INF/container.xml"))
            rootfile_path =  t.xpath("/u:container/u:rootfiles/u:rootfile",
                                        namespaces=namespaces)[0].get("full-path")

            t = etree.fromstring(z.read(rootfile_path))
            cover_meta = t.xpath("//opf:metadata/opf:meta[@name='cover']",
                                        namespaces=namespaces)
            if not cover_meta:
                print("No cover image found.")
                return None
            cover_id = cover_meta[0].get("content")

            cover_item = t.xpath("//opf:manifest/opf:item[@id='" + cover_id + "']",
                                            namespaces=namespaces)
            if not cover_item:
                print("No cover image found.")
                return None
            cover_href = cover_item[0].get("href")
            cover_path = os.path.join(os.path.dirname(rootfile_path), cover_href)
            if os.name == 'nt' and '\\' in cover_path:
                cover_path = cover_path.replace("\\", "/")
            return z.open(cover_path)
    except FileNotFoundError:
        print(f"Could not get cover image of {epub_path}")

def export(book, sourcefile):
    book_contents = []
    cover_image = get_epub_cover(sourcefile)
    image_path = None

    if cover_image is not None:
        image = Image.open(cover_image)
        image_filename = sourcefile.replace(".epub", ".png")
        image_path = os.path.join(image_filename)
        image.save(image_path)
        print(f"Cover image saved to {image_path}")

    # Get the table of contents
    toc = book.get_toc() if hasattr(book, 'get_toc') else []

    spine_ids = [spine_tuple[0] for spine_tuple in book.spine if spine_tuple[1] == 'yes']
    items = {item.get_id(): item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT}

    for id in spine_ids:
        item = items.get(id)
        if item is None:
            continue
        # Pass item_id and toc to chap2text_epub
        chapter_title, chapter_paragraphs = chap2text_epub(item.get_content(), item_id=id, toc=toc)
        book_contents.append({"title": chapter_title, "paragraphs": chapter_paragraphs})

    outfile = sourcefile.replace(".epub", ".txt")
    check_for_file(outfile)
    print(f"Exporting {sourcefile} to {outfile}")
    author = book.get_metadata("DC", "creator")[0][0]
    booktitle = book.get_metadata("DC", "title")[0][0]

    with open(outfile, "w", encoding='utf-8') as file:
        file.write(f"Title: {booktitle}\n")
        file.write(f"Author: {author}\n\n")
        file.write(f"# Title\n")
        file.write(f"{booktitle}, by {author}\n\n")
        for i, chapter in enumerate(book_contents, start=1):
            if not chapter["paragraphs"] or chapter["paragraphs"] == ['']:
                continue
            else:
                # Use chapter title if available, otherwise fallback to "Part {i}"
                title = chapter["title"] if chapter["title"] else f"Part {i}"
                file.write(f"# {title}\n\n")
                for paragraph in chapter["paragraphs"]:
                    clean = re.sub(r'[\s\n]+', ' ', paragraph)
                    # Normalize common curly quotes to straight quotes using simple replacements
                    clean = clean.replace('“', '"').replace('”', '"')
                    clean = clean.replace('‘', "'").replace('’', "'")
                    clean = clean.replace('--', ', ').replace('—', ', ')
                    clean = re.sub(r'[""]', '"', clean)  # Curly double quotes to standard double quotes
                    clean = re.sub(r'[‘’]', "'", clean)  # Curly single quotes to standard single quotes
                    clean = re.sub(r'--', ', ', clean)
                    clean = re.sub(r'—', ', ', clean)
                    file.write(f"{clean}\n\n")

    return book_contents

def get_book(sourcefile):
    book_contents = []
    book_title = sourcefile
    book_author = "Unknown"
    chapter_titles = []

    with open(sourcefile, "r", encoding="utf-8") as file:
        current_chapter = {"title": "blank", "paragraphs": []}
        initialized_first_chapter = False
        lines_skipped = 0
        for line in file:

            if lines_skipped < 2 and (line.startswith("Title") or line.startswith("Author")):
                lines_skipped += 1
                if line.startswith('Title: '):
                    book_title = line.replace('Title: ', '').strip()
                elif line.startswith('Author: '):
                    book_author = line.replace('Author: ', '').strip()
                continue

            line = line.strip()
            if line.startswith("#"):
                if current_chapter["paragraphs"] or not initialized_first_chapter:
                    if initialized_first_chapter:
                        book_contents.append(current_chapter)
                    current_chapter = {"title": None, "paragraphs": []}
                    initialized_first_chapter = True
                chapter_title = line[1:].strip()
                if any(c.isalnum() for c in chapter_title):
                    current_chapter["title"] = chapter_title
                    chapter_titles.append(current_chapter["title"])
                else:
                    current_chapter["title"] = "blank"
                    chapter_titles.append("blank")
            elif line:
                if not initialized_first_chapter:
                    chapter_titles.append("blank")
                    initialized_first_chapter = True
                if any(char.isalnum() for char in line):
                    current_chapter["paragraphs"].append(line)

        # Append the last chapter if it contains any paragraphs.
        if current_chapter["paragraphs"]:
            book_contents.append(current_chapter)

    return book_contents, book_title, book_author, chapter_titles

def sort_key(s):
    # extract number from the string
    return int(re.findall(r'\d+', s)[0])

def check_for_file(filename):
    if os.path.isfile(filename):
        print(f"The file '{filename}' already exists.")
        overwrite = input("Do you want to overwrite the file? (y/n): ")
        if overwrite.lower() != 'y':
            print("Exiting without overwriting the file.")
            sys.exit()
        else:
            os.remove(filename)

def append_silence(tempfile, duration=1200):
    # if tempfile does not exist, return
    if not os.path.isfile(tempfile):
        print(f"File {tempfile} does not exist, skipping silence append.")
        return
    audio = AudioSegment.from_file(tempfile)
    # Create a silence segment
    silence = AudioSegment.silent(duration)
    # Append the silence segment to the audio
    combined = audio + silence
    # Save the combined audio back to file
    combined.export(tempfile, format="wav")

def combine_short_paragraphs(paragraphs, min_words=6):
    """
    Combine paragraphs that consist of a single sentence <min_words with next paragraph.
    """
    if not paragraphs:
        return []

    result = []
    i = 0

    while i < len(paragraphs):
        paragraph = paragraphs[i]

        # Check if this is a single short sentence
        sentences = sent_tokenize(paragraph)
        if len(sentences) == 1 and len(paragraph.split()) < min_words:
            # Combine with next paragraph if available
            if i + 1 < len(paragraphs):
                combined = paragraph + " " + paragraphs[i + 1]
                result.append(combined)
                i += 2  # Skip next paragraph
            else:
                # Last paragraph, just add it
                result.append(paragraph)
                i += 1
        else:
            result.append(paragraph)
            i += 1

    return result

def normalize_language_id(language):
    if not language:
        return "en"

    normalized = language.strip().lower()
    language_map = {
        "arabic": "ar",
        "danish": "da",
        "german": "de",
        "greek": "el",
        "english": "en",
        "spanish": "es",
        "finnish": "fi",
        "french": "fr",
        "hebrew": "he",
        "hindi": "hi",
        "italian": "it",
        "japanese": "ja",
        "korean": "ko",
        "malay": "ms",
        "dutch": "nl",
        "norwegian": "no",
        "polish": "pl",
        "portuguese": "pt",
        "russian": "ru",
        "swedish": "sv",
        "swahili": "sw",
        "turkish": "tr",
        "chinese": "zh",
    }
    return language_map.get(normalized, normalized)

def split_paragraph_for_tts(paragraph, max_chars=1200):
    """Split long paragraphs into predictable chunks for stable VRAM usage."""
    text = paragraph.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks = []
    current = ""

    for sentence in sent_tokenize(text):
        sentence = sentence.strip()
        if not sentence:
            continue

        # If a single sentence is still too long, split by words.
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            words = sentence.split()
            word_chunk = ""
            for word in words:
                candidate = f"{word_chunk} {word}".strip()
                if len(candidate) <= max_chars:
                    word_chunk = candidate
                else:
                    if word_chunk:
                        chunks.append(word_chunk)
                    word_chunk = word
            if word_chunk:
                chunks.append(word_chunk)
            continue

        candidate = f"{current} {sentence}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)

    return chunks

def estimate_max_new_tokens(text):
    """Estimate how many audio frames a text needs.

    Audio8 emits one token per ~21.5 Hz audio frame; audiobook narration
    runs at roughly 11-15 chars/sec. Estimate generously (the model itself
    caps generation to fit its context window).
    """
    estimated = int(len(text) * 1.95) + 128
    return max(512, min(estimated, 4096))

def audio8_generate_and_save(paragraph, processor, model, output_path, device,
                             reference_audio_path=None, reference_text=None):
    """Generate audio for `paragraph` using Audio8 and save to `output_path`."""
    clean_text = paragraph.strip()

    processor_kwargs = {
        "text": [clean_text],
        "return_tensors": "pt",
    }
    if reference_audio_path:
        processor_kwargs["reference_audio"] = [reference_audio_path]
        processor_kwargs["reference_text"] = [reference_text]

    try:
        inputs = processor(**processor_kwargs)
    except Exception as e:
        raise RuntimeError(f"Failed to prepare Audio8 inputs: {e}") from e

    inputs = {name: value.to(device) for name, value in inputs.items()}

    if "reference_audio_lengths" in inputs:
        ref_frames = int(inputs["reference_audio_lengths"][0]) // int(
            model.config.codec_frame_size
        )
        if ref_frames >= 1900:
            raise RuntimeError(
                f"Reference audio is too long ({ref_frames} codec frames; the model context "
                "fits about 2000). Use a shorter reference clip (10-30s) or reduce "
                "--reference-seconds."
            )

    max_new_tokens = estimate_max_new_tokens(clean_text)
    try:
        with torch.inference_mode():
            output = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=0.8,
                top_p=0.95,
                top_k=50,
                do_sample=True,
                return_dict_in_generate=True,
            )
            code_length = int(output.code_lengths[0])
            codes = output.codes[0, :, :code_length].unsqueeze(0)
            waveforms, waveform_lengths = model.decode_audio(codes)
            wav_np = waveforms[0, : int(waveform_lengths[0])].float().cpu().numpy()
    except RuntimeError as e:
        if "out of memory" in str(e).lower():
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
            raise RuntimeError(
                "GPU out of memory while generating audio. "
                "Try reducing --max-paragraph-chars (for example 1000 or 800)."
            ) from e
        raise

    if not output.finished[0]:
        print("Warning: generation hit the model's context limit before reaching the end "
              "of this paragraph. Consider lowering --max-paragraph-chars.")

    sf.write(output_path, wav_np, int(model.config.codec_sample_rate))

def resolve_voice_prompt(voice_prompt, legacy_speaker, sourcefile=None):
    candidate = voice_prompt or legacy_speaker
    if not candidate:
        return None
    if os.path.isfile(candidate):
        return candidate

    # Fall back to resolving relative to the script and the source file.
    bases = [os.path.dirname(os.path.abspath(__file__))]
    if sourcefile:
        bases.append(os.path.dirname(os.path.abspath(sourcefile)))
    candidates = [candidate, os.path.basename(candidate)]
    for base in bases:
        for name in candidates:
            alt = os.path.join(base, name)
            if os.path.isfile(alt):
                print(f"Reference audio resolved to: {alt}")
                return alt

    print(
        "Warning: Audio8 does not support named built-in speakers. "
        f"Value '{candidate}' was not found as an audio file and will be ignored."
    )
    return None

def prepare_reference_audio(reference_path, max_reference_seconds=30):
    """Convert the reference clip to a readable 44.1kHz mono WAV and trim it.

    Audio8 conditions on the whole reference clip, so it must be short enough
    to fit the model's 2048-frame context (~90s absolute, 10-30s recommended).

    Returns:
        tuple: (wav_path, temporary_flag)
    """
    import tempfile

    path = reference_path
    temporary = False

    # If soundfile cannot read the file (e.g. .opus), convert with ffmpeg.
    try:
        sf.read(path, dtype="float32")
    except Exception:
        temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temp_wav.close()
        print(f"Reference audio not directly readable; converting {reference_path} to WAV via ffmpeg")
        subprocess.run(
            ["ffmpeg", "-y", "-i", reference_path, "-ar", "44100", "-ac", "1", temp_wav.name],
            check=True,
            capture_output=True,
        )
        path = temp_wav.name
        temporary = True

    data, sample_rate = sf.read(path, dtype="float32")
    max_samples = int(max_reference_seconds * sample_rate)
    if len(data) > max_samples:
        if not temporary:
            temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_wav.close()
            path = temp_wav.name
            temporary = True
        sf.write(path, data[:max_samples], sample_rate)
        print(f"Reference audio trimmed to the first {max_reference_seconds}s; "
              "--voice-text must be the transcript of that segment.")

    return path, temporary

def transcribe_reference(audio_path, device, model_name="small"):
    """Transcribe a reference clip with faster-whisper so --voice-text isn't needed.

    Returns the transcript string, or None if faster-whisper is unavailable.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper is not installed; skipping automatic transcription.")
        return None

    whisper_device = device if device in ("cuda", "cpu") else "cpu"
    combos = []
    if whisper_device == "cuda":
        capability = torch.cuda.get_device_capability(0)
        if capability[0] >= 7:
            gpu_types = ["float16", "int8_float16", "int8", "float32"]
        elif capability[0] == 6:
            gpu_types = ["int8", "int8_float16", "float16", "float32"]
        else:
            gpu_types = ["float32"]
        combos += [("cuda", t) for t in gpu_types]
    combos += [("cpu", "int8"), ("cpu", "float32")]

    text = None
    used = None
    for dev, compute_type in combos:
        print(f"Transcribing reference audio with faster-whisper ({model_name}, {dev}, {compute_type})...")
        model = None
        try:
            model = WhisperModel(model_name, device=dev, compute_type=compute_type)
            segments, _ = model.transcribe(audio_path)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            used = (dev, compute_type)
            break
        except Exception as e:
            print(f"  {dev}/{compute_type} failed: {e}")
        finally:
            try:
                del model
            except Exception:
                pass
            if dev == "cuda":
                torch.cuda.empty_cache()

    if text:
        print(f"Reference transcript (auto): {text}")
    return text or None

def read_book(book_contents, voice_prompt, legacy_speaker, notitles, language, forced_device=None, max_paragraph_chars=1200, voice_text=None, reference_seconds=30, transcribe_model="small"):
    """
    Read the book contents and generate per-chapter WAV files using Audio8.

    If `forced_device` is provided it will be used instead of auto-detection.
    """
    # Determine device: prefer forced_device when provided
    if forced_device:
        device = forced_device
    else:
        if torch.cuda.is_available():
            device = "cuda"
        elif torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

    print(f"Using device: {device}")
    print(f"Max paragraph chunk length for TTS: {max_paragraph_chars} chars")

    normalize_language_id(language)
    audio_prompt_path = resolve_voice_prompt(voice_prompt, legacy_speaker, sourcefile=None)

    reference_tmp = None
    if audio_prompt_path:
        audio_prompt_path, reference_tmp = prepare_reference_audio(audio_prompt_path, reference_seconds)

    reference_text = None
    if voice_text and os.path.isfile(voice_text):
        with open(voice_text, "r", encoding="utf-8") as f:
            reference_text = f.read().strip()
        print(f"Reference transcript loaded from file: {voice_text}")
    elif voice_text:
        reference_text = voice_text.strip()

    if audio_prompt_path and not reference_text:
        reference_text = transcribe_reference(audio_prompt_path, device, model_name=transcribe_model)
        if not reference_text:
            print("\nAudio8 zero-shot voice cloning needs the transcript of the reference clip")
            print("(the words actually spoken in '{}').".format(audio_prompt_path))
            reference_text = input("Paste the transcript here: ").strip()
        if not reference_text:
            raise ValueError(
                "A reference transcript is required for voice cloning. "
                "Provide it with --voice-text \"...\" or as --voice-text transcript.txt"
            )

    print("Loading Audio8 model (lazy import to avoid import-time dependency issues)")
    model_id = "Edge0/Audio8-TTS-Realistic-Air"
    try:
        from transformers import AutoModel, AutoProcessor

        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        model = AutoModel.from_pretrained(
            model_id, trust_remote_code=True, dtype=dtype
        ).eval().to(device)
    except Exception as e:
        raise RuntimeError(
            f"Could not import or load Audio8: {e}\n"
            "If you only want to export the EPUB to text, run the script again after exporting or install the proper Audio8 dependencies."
        )

    # Initialize timing and progress tracking
    start_time = time.time()
    total_chars = sum(len(''.join(chapter['paragraphs'])) for chapter in book_contents)
    processed_chars = 0

    segments = []
    for i, chapter in enumerate(book_contents, start=1):
        paragraphpause = 600  # default pause between paragraphs in ms
        files = []
        partname = f"part{i}.wav"
        print(f"\n\n")

        if os.path.isfile(partname):
            print(f"{partname} exists, skipping to next chapter")
            segments.append(partname)
            # Track characters even for skipped chapters
            processed_chars += len(''.join(chapter['paragraphs']))
        else:
            # Calculate timing info before processing this chapter
            elapsed_time = time.time() - start_time
            elapsed_str = format_time_adaptive(elapsed_time)

            # Calculate ETA based on text processed
            if processed_chars > 0:
                time_per_char = elapsed_time / processed_chars
                remaining_chars = total_chars - processed_chars
                eta_seconds = remaining_chars * time_per_char
                eta_str = format_time_adaptive(eta_seconds)
                timing_info = f" | Elapsed: {elapsed_str} | ETA: {eta_str}"
            else:
                timing_info = f" | Elapsed: {elapsed_str}"

            print(f"Chapter ({i}/{len(book_contents)}): {chapter['title']}{timing_info}\n")
            print(f"Section name: \"{chapter['title']}\"")
            if chapter["title"] == "":
                chapter["title"] = "blank"
            if chapter["title"] != "Title" and notitles != True:
                chapter['paragraphs'][0] = chapter['title'] + ". " + chapter['paragraphs'][0]

            # Combine short paragraphs
            combined_paragraphs = combine_short_paragraphs(chapter["paragraphs"])

            for pindex, paragraph in enumerate(combined_paragraphs):
                ptemp = f"pgraph{pindex}.wav"
                if os.path.isfile(ptemp):
                    print(f"{ptemp} exists, skipping to next paragraph")
                else:
                    # Generate audio for paragraph/chunks with Audio8
                    print(f"Generating audio for paragraph {pindex+1}/{len(combined_paragraphs)}")
                    print(f"Paragraph length: {len(paragraph)}")

                    paragraph_chunks = split_paragraph_for_tts(paragraph, max_chars=max_paragraph_chars)
                    print(f"Chunk count: {len(paragraph_chunks)}")

                    if len(paragraph_chunks) == 1:
                        audio8_generate_and_save(
                            paragraph_chunks[0],
                            processor,
                            model,
                            ptemp,
                            device,
                            reference_audio_path=audio_prompt_path,
                            reference_text=reference_text,
                        )
                    else:
                        chunk_files = []
                        for chunk_index, chunk_text in enumerate(paragraph_chunks):
                            chunk_file = f"pgraph{pindex}_chunk{chunk_index}.wav"
                            audio8_generate_and_save(
                                chunk_text,
                                processor,
                                model,
                                chunk_file,
                                device,
                                reference_audio_path=audio_prompt_path,
                                reference_text=reference_text,
                            )
                            chunk_files.append(chunk_file)

                        combined_chunks = AudioSegment.empty()
                        for chunk_file in chunk_files:
                            combined_chunks += AudioSegment.from_file(chunk_file)
                        combined_chunks.export(ptemp, format="wav")
                        for chunk_file in chunk_files:
                            os.remove(chunk_file)

                    # Add silence at end of paragraph
                    if pindex < len(combined_paragraphs) - 1:
                        append_silence(ptemp, paragraphpause)

                files.append(ptemp)

            # Combine paragraphs into chapter
            append_silence(files[-1], 2000)
            combined = AudioSegment.empty()
            for file in files:
                combined += AudioSegment.from_file(file)
            combined.export(partname, format="wav")
            for file in files:
                os.remove(file)
            segments.append(partname)
            # Track processed characters for this chapter
            processed_chars += len(''.join(chapter['paragraphs']))

    if reference_tmp:
        try:
            os.remove(reference_tmp)
        except OSError:
            pass

    return segments

def generate_metadata(files, author, title, chapter_titles):
    chap = 0
    start_time = 0
    with open("FFMETADATAFILE", "w") as file:
        file.write(";FFMETADATA1\n")
        file.write(f"ARTIST={author}\n")
        file.write(f"ALBUM={title}\n")
        file.write(f"TITLE={title}\n")
        file.write("DESCRIPTION=Made with Audio8 TTS\n")
        for file_name in files:
            duration = get_duration(file_name)
            file.write("[CHAPTER]\n")
            file.write("TIMEBASE=1/1000\n")
            file.write(f"START={start_time}\n")
            file.write(f"END={start_time + duration}\n")
            file.write(f"title={chapter_titles[chap]}\n")
            chap += 1
            start_time += duration

def get_duration(file_path):
    audio = AudioSegment.from_file(file_path)
    duration_milliseconds = len(audio)
    return duration_milliseconds

def make_m4b(files, sourcefile, speaker):
    filelist = "filelist.txt"
    basefile = sourcefile.replace(".txt", "")
    outputm4a = f"{basefile}.m4a"
    outputm4b = f"{basefile} ({speaker}).m4b"
    with open(filelist, "w") as f:
        for filename in files:
            filename = filename.replace("'", "'\\''")
            f.write(f"file '{filename}'\n")
    ffmpeg_command = [
        "ffmpeg",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        filelist,
        "-codec:a",
        "aac",
        "-f",
        "mp4",
        "-strict",
        "-2",
        outputm4a,
    ]
    subprocess.run(ffmpeg_command)
    ffmpeg_command = [
        "ffmpeg",
        "-i",
        outputm4a,
        "-i",
        "FFMETADATAFILE",
        "-map_metadata",
        "1",
        "-codec",
        "copy",
        outputm4b,
    ]
    subprocess.run(ffmpeg_command)
    os.remove(filelist)
    os.remove("FFMETADATAFILE")
    os.remove(outputm4a)
    for f in files:
        os.remove(f)
    return outputm4b

def add_cover(cover_img, filename):
    try:
        if os.path.isfile(cover_img):
            m4b = mp4.MP4(filename)
            cover_image = open(cover_img, "rb").read()
            m4b["covr"] = [mp4.MP4Cover(cover_image)]
            m4b.save()
        else:
            print(f"Cover image {cover_img} not found")
    except:
        print(f"Cover image {cover_img} not found")

def validate_text_file(sourcefile, book_title, book_author, book_contents):
    """
    Validate that the text file contains required elements: title, author, and at least one chapter break.

    Args:
        sourcefile: Path to the source file
        book_title: Extracted book title
        book_author: Extracted book author
        book_contents: List of chapter dictionaries

    Raises:
        SystemExit: If validation fails
    """
    errors = []

    # Check if title was found (if it's still the filename, no title was extracted)
    if book_title == sourcefile:
        errors.append("- Missing 'Title:' line at the beginning of the file")

    # Check if author was found
    if book_author == "Unknown":
        errors.append("- Missing 'Author:' line at the beginning of the file")

    # Check if at least one chapter break was found
    has_chapter_break = False
    with open(sourcefile, "r", encoding="utf-8") as file:
        for line in file:
            if line.strip().startswith("#"):
                has_chapter_break = True
                break

    if not has_chapter_break:
        errors.append("- Missing at least one chapter break line starting with '#'")

    # If there are any errors, display them and exit
    if errors:
        print("\n" + "="*70)
        print("ERROR: Text file validation failed")
        print("="*70)
        print("\nThe text file must contain the following elements:\n")
        print("1. A 'Title:' line at the beginning (e.g., 'Title: My Book')")
        print("2. An 'Author:' line at the beginning (e.g., 'Author: John Doe')")
        print("3. At least one chapter break line starting with '#' (e.g., '# Chapter 1')")
        print("\nMissing elements:")
        for error in errors:
            print(error)
        print("\nPlease correct the text file format and try again.")
        print("="*70 + "\n")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        prog="epub2tt_audio8.py",
        description="Read a text file to audiobook format using Audio8 TTS",
    )
    parser.add_argument("sourcefile", type=str, help="The epub or text file to process")
    parser.add_argument(
        "--speaker",
        type=str,
        help="Deprecated alias. If this is a valid audio file path, it will be used as Audio8 reference audio.",
    )
    parser.add_argument(
        "--voice",
        type=str,
        help="Optional reference audio file for Audio8 zero-shot voice cloning.",
    )
    parser.add_argument(
        "--voice-text",
        type=str,
        help="Transcript of the reference audio (inline text or a path to a .txt file). Required for voice cloning; if omitted you will be prompted. Must match the spoken content of the (trimmed) reference clip.",
    )
    parser.add_argument(
        "--reference-seconds",
        type=int,
        default=30,
        help="Trim the reference voice clip to this many seconds before cloning (default: 30). Audio8 only fits short references; --voice-text must be the transcript of the trimmed segment.",
    )
    parser.add_argument(
        "--transcribe-model",
        type=str,
        default="small",
        help="faster-whisper model used to auto-transcribe the reference clip when --voice-text is omitted (default: small). Sizes: tiny, base, small, medium, large-v3.",
    )
    parser.add_argument(
        "--language",
        type=str,
        default="en",
        help="Language code or name (default: en). Accepted for compatibility; Audio8 auto-detects the language from the text.",
    )
    parser.add_argument(
        "--model_path",
        type=str,
        help="Deprecated and ignored. Audio8 downloads its pretrained model automatically.",
    )
    parser.add_argument(
        "--cover",
        type=str,
        help="Image file to use for cover (jpg or png)",
    )
    parser.add_argument(
        "--notitles",
        action="store_true",
        help="Do not read chapter titles"
    )
    parser.add_argument(
        "--device",
        type=str,
        choices=["cuda", "mps", "cpu"],
        help="Force device to use (overrides auto-detection).",
    )
    parser.add_argument(
        "--max-paragraph-chars",
        type=int,
        default=1200,
        help="Maximum chars sent to TTS per chunk (default: 1200). Reduce this if your GPU runs out of memory.",
    )

    args = parser.parse_args()
    print(args)

    ensure_punkt()

    # If we get an epub, export that to txt file, then exit
    if args.sourcefile.endswith(".epub"):
        book = epub.read_epub(args.sourcefile)
        export(book, args.sourcefile)
        exit()

    book_contents, book_title, book_author, chapter_titles = get_book(args.sourcefile)

    # Validate the text file before proceeding
    validate_text_file(args.sourcefile, book_title, book_author, book_contents)

    resolved_voice_prompt = resolve_voice_prompt(args.voice, args.speaker, sourcefile=args.sourcefile)

    files = read_book(
        book_contents,
        resolved_voice_prompt,
        None,
        args.notitles,
        args.language,
        forced_device=args.device,
        max_paragraph_chars=args.max_paragraph_chars,
        voice_text=args.voice_text,
        reference_seconds=args.reference_seconds,
        transcribe_model=args.transcribe_model,
    )
    generate_metadata(files, book_author, book_title, chapter_titles)
    voice_label = os.path.splitext(os.path.basename(resolved_voice_prompt))[0] if resolved_voice_prompt else "default"
    m4bfilename = make_m4b(files, args.sourcefile, voice_label)
    if args.cover:
        add_cover(args.cover, m4bfilename)

    print(f"\n{'='*50}")
    print(f"Audiobook created successfully: {m4bfilename}")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
