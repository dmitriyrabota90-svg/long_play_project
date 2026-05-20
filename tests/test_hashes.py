from app.storage.hashes import stable_json_hash


def test_stable_json_hash_is_stable_for_key_order() -> None:
    left = {"b": 2, "a": {"d": 4, "c": 3}}
    right = {"a": {"c": 3, "d": 4}, "b": 2}

    assert stable_json_hash(left) == stable_json_hash(right)

