from __future__ import annotations

from atelier.core.foundation.redaction import redact, redact_list


def test_redacts_openai_key() -> None:
    assert "sk-" not in redact("token sk-ABCDEFGHIJKLMNOPQRSTUV1234567890")


def test_redacts_credential_pair() -> None:
    assert "<redacted-credential>" in redact("api_key=supersecretthing123")


def test_redacts_chain_of_thought_marker() -> None:
    out = redact("step 1 fine\nchain of thought: secret reasoning here")
    assert "<redacted-hidden-reasoning>" in out
    assert "secret reasoning" not in out


def test_redacts_jwt() -> None:
    jwt = "eyJABCDEFGHIJ.eyJABCDEFGHIJ.signaturepartXYZ"
    assert "<redacted-jwt>" in redact(f"Bearer {jwt}")


def test_redact_list_applies_per_item() -> None:
    out = redact_list(["clean", "password=hunter2"])
    assert out[0] == "clean"
    assert "<redacted-credential>" in out[1]
