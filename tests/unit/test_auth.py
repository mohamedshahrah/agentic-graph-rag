"""API-key format. Storage and lookup moved to Postgres and are covered by the
integration suite, which exercises them against a real database."""

from graphrag.auth import generate_api_key, hash_key


def test_keys_are_prefixed_and_long_enough_to_be_unguessable():
    key = generate_api_key()
    assert key.startswith("grk_")
    assert len(key) > 40


def test_every_key_is_unique():
    assert len({generate_api_key() for _ in range(100)}) == 100


def test_hashing_is_stable_and_one_way():
    key = generate_api_key()
    assert hash_key(key) == hash_key(key)
    assert key not in hash_key(key)
    assert len(hash_key(key)) == 64  # sha256 hex


def test_different_keys_hash_differently():
    assert hash_key(generate_api_key()) != hash_key(generate_api_key())
