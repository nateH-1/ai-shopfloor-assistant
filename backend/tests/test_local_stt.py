"""Local speech contracts: no model download or live inference in unit tests."""
from io import BytesIO
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask
import pytest

import local_stt


@pytest.fixture
def system(monkeypatch, tmp_path):
    monkeypatch.setenv("STT_MODEL_PATH", str(tmp_path / "model"))
    app = Flask(__name__)
    local_stt.register_transcription(app)
    speech = app.extensions["local_stt"]
    model = Mock()
    model.transcribe.return_value = (iter([SimpleNamespace(text=" Heat treatment "), SimpleNamespace(text=" of steel. ")]), None)
    monkeypatch.setattr(speech, "model", Mock(return_value=model))
    monkeypatch.setattr(speech, "decode", Mock(return_value=[0.0] * 16000))
    return app.test_client(), speech, model


def upload(client, data=b"recording"):
    return client.post("/api/transcribe", data={"audio": (BytesIO(data), "recording.webm")})


def test_transcribes_without_openai_key_and_consumes_generator_under_lock(system, monkeypatch):
    client, speech, model = system
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    def segments():
        assert speech.lock.locked()
        yield SimpleNamespace(text=" Heat treatment of steel. ")
    model.transcribe.return_value = (segments(), None)
    response = upload(client)
    assert response.status_code == 200
    assert response.get_json() == {"text": "Heat treatment of steel."}
    assert model.transcribe.call_args.kwargs["vad_filter"] is True
    assert model.transcribe.call_args.kwargs["condition_on_previous_text"] is False
    assert not speech.lock.locked()


@pytest.mark.parametrize("empty", [False, True])
def test_missing_or_empty_audio_rejected_before_loading_model(system, empty):
    client, speech, _ = system
    response = upload(client, b"") if empty else client.post("/api/transcribe")
    assert response.status_code == 400
    speech.model.assert_not_called()


def test_invalid_audio_is_422_and_releases_lock(system):
    client, speech, _ = system
    speech.decode.side_effect = ValueError("invalid media")
    assert upload(client).status_code == 422
    assert not speech.lock.locked()


def test_silence_does_not_invent_transcript(system):
    client, _, model = system
    model.transcribe.return_value = (iter([]), None)
    response = upload(client)
    assert response.status_code == 422
    assert "No speech" in response.get_json()["error"]


def test_busy_returns_429_without_running_another_inference(system):
    client, speech, model = system
    speech.lock.acquire()
    try:
        assert upload(client).status_code == 429
        model.transcribe.assert_not_called()
    finally:
        speech.lock.release()


def test_excessive_duration_is_rejected(system):
    client, speech, model = system
    speech.max_seconds = 0
    assert upload(client).status_code == 413
    model.transcribe.assert_not_called()


def test_excessive_audio_size_is_rejected(system, monkeypatch):
    client, speech, _ = system
    monkeypatch.setattr(local_stt, "MAX_AUDIO_BYTES", 10)
    assert upload(client, b"x" * 11).status_code == 413
    speech.model.assert_not_called()


def test_setup_failure_is_actionable_without_cloud_fallback(system):
    client, speech, _ = system
    speech.model.side_effect = local_stt.SpeechSetupError("Run backend/prepare_stt.py first.")
    response = upload(client)
    assert response.status_code == 503
    assert "prepare_stt" in response.get_json()["error"]
    speech.decode.assert_not_called()


def test_lazy_inference_failure_is_sanitized_and_releases_lock(system):
    client, speech, model = system
    def broken():
        raise RuntimeError("private system details")
        yield
    model.transcribe.return_value = (broken(), None)
    response = upload(client)
    assert response.status_code == 503
    assert "private" not in response.get_data(as_text=True)
    assert not speech.lock.locked()


def test_model_requires_complete_local_files_and_never_downloads(monkeypatch, tmp_path):
    monkeypatch.setenv("STT_MODEL_PATH", str(tmp_path))
    speech = local_stt.LocalSpeech()
    constructor = Mock()
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=constructor))
    with pytest.raises(local_stt.SpeechSetupError):
        speech.model()
    constructor.assert_not_called()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (tmp_path / name).touch()
    assert speech.model() is constructor.return_value
    assert speech.model() is constructor.return_value
    constructor.assert_called_once_with(str(tmp_path.resolve()), device="cpu", compute_type="int8", local_files_only=True)


def test_auto_language_is_passed_to_local_model(system):
    client, speech, model = system
    speech.language = "auto"
    assert upload(client).status_code == 200
    assert model.transcribe.call_args.kwargs["language"] is None


def test_health_does_not_load_model(system):
    client, speech, _ = system
    payload = client.get("/api/transcribe/health").get_json()
    assert payload["provider"] == "local"
    assert payload["loaded"] is False
    speech.model.assert_not_called()


def _microphone_webm() -> bytes:
    """A real WebM/Opus file, the container a browser microphone records."""
    import av
    import numpy as np

    buf = BytesIO()
    with av.open(buf, "w", format="webm") as container:
        stream = container.add_stream("libopus", rate=48000)
        stream.layout = "mono"
        frame_size = 960  # 20 ms, the Opus frame size at 48 kHz
        tone = (np.sin(2 * np.pi * 440 * np.arange(48000) / 48000) * 8000).astype(np.int16)
        for start in range(0, len(tone), frame_size):
            frame = av.AudioFrame(format="s16", layout="mono", samples=frame_size)
            frame.sample_rate = 48000
            frame.planes[0].update(tone[start:start + frame_size].tobytes())
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return buf.getvalue()


def test_transcribe_decodes_webm_opus_recording(monkeypatch):
    import av

    # PyAV 19 removed metadata_errors, which faster-whisper 1.2.1 still passes.
    assert int(av.__version__.split(".")[0]) < 19
    app = Flask(__name__)
    local_stt.register_transcription(app)
    speech = app.extensions["local_stt"]
    decoded = {}
    model = Mock()

    def transcribe(audio, **kwargs):
        decoded["samples"] = len(audio)
        return iter([SimpleNamespace(text="heat treatment")]), None

    model.transcribe.side_effect = transcribe
    monkeypatch.setattr(speech, "model", lambda: model)
    recording = _microphone_webm()
    assert recording[:4] == b"\x1a\x45\xdf\xa3"
    response = app.test_client().post(
        "/api/transcribe",
        data={"audio": (BytesIO(recording), "recording.webm")},
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json() == {"text": "heat treatment"}
    assert decoded["samples"] >= 16000
