from orchestrator.evidence import EvidenceChain


def test_chain_appends_and_links(tmp_path):
    chain = EvidenceChain(tmp_path / "t.jsonl")
    chain.append("lane1", "claimed", {"worker": "h1"})
    chain.append("lane4", "harness_run", {"lines": 10})
    entries = chain.entries()
    assert len(entries) == 2
    assert entries[0].prev == "0" * 64
    assert entries[1].prev == entries[0].hash
    ok, reason = chain.verify_chain()
    assert ok, reason


def test_tamper_detected(tmp_path):
    path = tmp_path / "t.jsonl"
    chain = EvidenceChain(path)
    chain.append("lane1", "claimed", {"worker": "h1"})
    chain.append("lane6", "verify_passed", {"checks": ["x"]})
    # Tamper with the first line's detail.
    lines = path.read_text().splitlines()
    lines[0] = lines[0].replace('"h1"', '"attacker"')
    path.write_text("\n".join(lines) + "\n")
    ok, reason = chain.verify_chain()
    assert not ok
    assert "hash mismatch" in reason


def test_seal_and_verify(tmp_path):
    chain = EvidenceChain(tmp_path / "t.jsonl")
    chain.append("lane1", "claimed", {})
    chain.append("lane6", "verify_passed", {})
    key = b"unit-test-key"
    chain.seal(key)
    assert chain.verify_seal(key) is True
    assert chain.verify_seal(b"wrong-key") is False


def test_seal_refuses_broken_chain(tmp_path):
    path = tmp_path / "t.jsonl"
    chain = EvidenceChain(path)
    chain.append("lane1", "claimed", {"x": 1})
    lines = path.read_text().splitlines()
    lines[0] = lines[0].replace('"x": 1', '"x": 2')
    assert lines[0].count('"x": 2') == 1  # guard: tamper actually applied
    path.write_text("\n".join(lines) + "\n")
    try:
        chain.seal(b"k")
        assert False, "expected refusal"
    except ValueError as e:
        assert "broken chain" in str(e)
