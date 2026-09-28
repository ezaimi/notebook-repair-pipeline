import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import enrich_v2_provenance as provenance


def test_repository_provenance_uses_only_the_recorded_commit(monkeypatch):
    requested = []

    def fake_fetch(url):
        requested.append(url)
        if url.endswith("/commit/abc123.patch"):
            return b"From: test\nDate: Tue, 27 Dec 2022 18:57:29 +0000\n"
        if url.endswith("/abc123/requirements.txt"):
            return b"demo-package==1.0\n"
        raise AssertionError(f"unexpected fallback URL: {url}")

    monkeypatch.setattr(provenance, "fetch_bytes", fake_fetch)
    _, result = provenance._repository_provenance((5, {
        "repository": "org/repo", "commit": "abc123", "requirements": "requirements.txt",
        "setups": "setup.py",
    }))

    assert result["repository_commit"] == "abc123"
    assert result["repository_commit_date"] == "2022-12-27T18:57:29+00:00"
    assert result["provenance_status"] == "recorded_commit_and_date"
    assert result["dependency_file_metadata"][0]["ref"] == "abc123"
    assert result["repository_setup_paths"] == ["setup.py"]
    assert all("main" not in url and "master" not in url for url in requested)
