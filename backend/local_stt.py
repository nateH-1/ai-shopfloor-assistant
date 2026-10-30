"""Local-only speech recognition; no audio is forwarded to a cloud service."""
from io import BytesIO
import logging
import os
from pathlib import Path
from threading import Lock

from flask import Blueprint, jsonify, request

MAX_AUDIO_BYTES = 25 * 1024 * 1024
SAMPLE_RATE = 16000
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / ".models" / "whisper-base.en"
logger = logging.getLogger(__name__)


class SpeechSetupError(RuntimeError):
    pass


class LocalSpeech:
    def __init__(self):
        self.model_path = Path(os.getenv("STT_MODEL_PATH", str(DEFAULT_MODEL_PATH))).expanduser().resolve()
        self.device = os.getenv("STT_DEVICE", "cpu")
        self.compute_type = os.getenv("STT_COMPUTE_TYPE", "int8")
        self.language = os.getenv("STT_LANGUAGE", "en")
        self.max_seconds = int(os.getenv("STT_MAX_SECONDS", "120"))
        self._model = None
        self.lock = Lock()

    def model(self):
        # Only called under lock. Missing files are an error, never a cloud fallback.
        if self._model is None:
            if not all((self.model_path / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json")):
                raise SpeechSetupError("Local speech model is missing or incomplete. Run backend/prepare_stt.py first.")
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise SpeechSetupError("Install backend/requirements.txt to enable local speech-to-text.") from exc
            self._model = WhisperModel(
                str(self.model_path), device=self.device, compute_type=self.compute_type,
                local_files_only=True,
            )
        return self._model

    @staticmethod
    def decode(data):
        from faster_whisper.audio import decode_audio
        return decode_audio(BytesIO(data), sampling_rate=SAMPLE_RATE)


def register_transcription(app):
    speech = LocalSpeech()
    app.extensions["local_stt"] = speech
    bp = Blueprint("local_stt", __name__)

    @bp.get("/api/transcribe/health")
    def health():
        return jsonify(provider="local", model=speech.model_path.name,
                       model_downloaded=all((speech.model_path / name).is_file()
                                            for name in ("model.bin", "config.json", "tokenizer.json")),
                       loaded=speech._model is not None, device=speech.device)

    @bp.post("/api/transcribe")
    def transcribe():
        # Leave room for multipart headers; the audio itself has an exact limit.
        if request.content_length and request.content_length > MAX_AUDIO_BYTES + 65536:
            return jsonify(error="Audio file exceeds the 25 MB limit."), 413
        upload = request.files.get("audio")
        if upload is None:
            return jsonify(error="Missing audio file. Send an 'audio' form field."), 400
        data = upload.stream.read(MAX_AUDIO_BYTES + 1)
        if not data:
            return jsonify(error="Audio file is empty."), 400
        if len(data) > MAX_AUDIO_BYTES:
            return jsonify(error="Audio file exceeds the 25 MB limit."), 413
        if not speech.lock.acquire(blocking=False):
            return jsonify(error="Another recording is being transcribed. Please try again shortly."), 429
        try:
            try:
                model = speech.model()
            except SpeechSetupError as exc:
                return jsonify(error=str(exc)), 503
            try:
                audio = speech.decode(data)
            except Exception:
                return jsonify(error="The recording could not be decoded. Try recording it again."), 422
            if len(audio) > SAMPLE_RATE * speech.max_seconds:
                return jsonify(error=f"Keep recordings to {speech.max_seconds} seconds or less."), 413
            segments, _ = model.transcribe(
                audio, language=None if speech.language == "auto" else speech.language,
                vad_filter=True, beam_size=5, temperature=0, condition_on_previous_text=False,
            )
            # faster-whisper returns a lazy generator; consume it while holding the lock.
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
            if not text:
                return jsonify(error="No speech was detected. Please try speaking again."), 422
            return jsonify(text=text)
        except Exception:
            logger.exception("Local transcription failed")
            return jsonify(error="Local transcription failed. Check the local speech model setup."), 503
        finally:
            speech.lock.release()

    app.register_blueprint(bp)
