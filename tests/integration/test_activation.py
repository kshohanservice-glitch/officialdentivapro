"""Activation end-to-end: correct/incorrect code, tamper detection, normalization."""
from __future__ import annotations

import pytest
from dentiva.activation import machine, verifier
from dentiva.core.errors import ActivationError


@pytest.fixture(autouse=True)
def _isolate_activation(tmp_data_dir, monkeypatch):
    """Ensure activation reads/writes under the per-test tmp_data_dir and
    uses a deterministic machine fingerprint (no host-dependent data).

    The tmp_data_dir fixture already redirects paths via monkeypatch. We
    additionally stub machine_fingerprint so tests are deterministic.
    """
    import dentiva.paths
    monkeypatch.setattr(machine, "paths", dentiva.paths.paths)
    monkeypatch.setattr(verifier, "paths", dentiva.paths.paths)
    monkeypatch.setattr(machine, "machine_fingerprint", lambda: "test-fingerprint")
    yield


def test_correct_code_activates():
    assert not verifier.is_activated()
    verifier.activate("1516591935015165")
    assert verifier.is_activated()


def test_wrong_code_rejected():
    with pytest.raises(ActivationError):
        verifier.activate("0000000000000000")
    assert not verifier.is_activated()


def test_tampered_activation_is_rejected():
    verifier.activate("1516591935015165")
    p = verifier._activation_path()
    p.write_text(p.read_text().replace("dentiva-pro", "tampered"), encoding="utf-8")
    assert not verifier.is_activated()


def test_normalization_ignores_spaces_and_dashes():
    verifier.activate(" 15165-9193-5015-165 ")
    assert verifier.is_activated()
