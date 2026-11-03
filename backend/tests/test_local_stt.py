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
