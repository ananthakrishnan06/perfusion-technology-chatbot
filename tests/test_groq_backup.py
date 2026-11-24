import pytest
from groq import AuthenticationError
import httpx
from unittest.mock import Mock
from generation.groq_client import GroqClientWrapper, GroqConfigurationError
from config import settings


@pytest.mark.parametrize("audio,stream", [(False, False), (False, True), (True, False)])
def test_groq_backup_after_rejected_key(monkeypatch, audio, stream):
    monkeypatch.setattr(settings, "GROQ_BACKUP_API_KEY", "test-backup")
    wrapper = GroqClientWrapper(api_key="test-primary")
    primary = Mock()
    backup = primary.with_options.return_value
    wrapper._client = primary
    request = httpx.Request("POST", "https://example.invalid")
    rejection = AuthenticationError("Rejected", response=httpx.Response(401, request=request), body=None)
    first = primary.audio.transcriptions if audio else primary.chat.completions
    second = backup.audio.transcriptions if audio else backup.chat.completions
    first.create.side_effect = rejection
    assert wrapper._create(audio=audio, stream=stream) is second.create.return_value
    primary.with_options.assert_called_once_with(api_key="test-backup")
    second.create.assert_called_once_with(stream=stream)
    second.create.side_effect = rejection
    with pytest.raises(GroqConfigurationError):
        wrapper._create(audio=audio, stream=stream)
