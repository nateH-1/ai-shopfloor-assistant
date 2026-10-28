"""One-time model download. Transcription itself uses local files only."""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="base.en", help="faster-whisper model size, e.g. base.en or small.en")
    parser.add_argument("--output", default=os.getenv("STT_MODEL_PATH", str(ROOT / ".models/whisper-base.en")))
    args = parser.parse_args()
    try:
        from faster_whisper.utils import download_model
    except ImportError:
        parser.exit(1, "Install dependencies first: python -m pip install -r backend/requirements-stt.txt\n")
    target = Path(args.output).expanduser().resolve()
    download_model(args.model, output_dir=str(target), cache_dir=str(ROOT / ".models/cache"))
    print(f"Local speech model ready: {target}")
    print("Inference uses local files only. Audio is never sent to a cloud service.")


if __name__ == "__main__":
    main()
