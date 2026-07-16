"""API-key store: keys resolve to users, are stored only as hashes, and revoke."""

from graphrag.auth import KeyStore, generate_api_key, hash_key


def test_key_roundtrip():
    ks = KeyStore(None)  # in-memory
    key = ks.create_key("alice")
    assert key.startswith("grk_")
    assert ks.resolve(key) == "alice"
    assert ks.resolve("grk_bogus") is None


def test_only_hash_is_stored():
    ks = KeyStore(None)
    key = ks.create_key("bob")
    assert key not in ks._mem           # plaintext never stored
    assert hash_key(key) in ks._mem     # only the hash


def test_hash_is_stable():
    k = generate_api_key()
    assert hash_key(k) == hash_key(k)


def test_revoke():
    ks = KeyStore(None)
    key = ks.create_key("carol")
    assert ks.revoke_user("carol") == 1
    assert ks.resolve(key) is None
