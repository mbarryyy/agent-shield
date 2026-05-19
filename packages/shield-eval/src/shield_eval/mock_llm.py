"""MockedLLM replaying scripted UserTask0/UserTask10/InjectionTask6 transcripts
(no API keys in PR CI). W0 STUB -> W1 eval-builder."""

from __future__ import annotations


class MockedLLM:
    def __init__(self, transcript: str = "") -> None:
        self.transcript = transcript
