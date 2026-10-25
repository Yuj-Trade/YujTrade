import pytest

from utils import security
from utils.security import (
    KeyEncryptor,
    generate_key_from_password,
    get_encryption_key,
    get_password_from_key_manager,
    hash_data,
    verify_hashed_data,
)

PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def _workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield tmp_path


class TestKeyDerivation:
    def test_same_password_and_salt_produce_the_same_key(self):
        salt = b"0123456789abcdef"

        first = generate_key_from_password(PASSWORD, salt)
        second = generate_key_from_password(PASSWORD, salt)

        assert first == second

    def test_a_different_salt_produces_a_different_key(self):
        first = generate_key_from_password(PASSWORD, b"a" * 16)
        second = generate_key_from_password(PASSWORD, b"b" * 16)

        assert first != second

    def test_key_is_a_valid_fernet_key(self):
        from cryptography.fernet import Fernet

        key = generate_key_from_password(PASSWORD, b"c" * 16)

        assert Fernet(key) is not None

    def test_missing_salt_file_is_created_once_and_reused(self, _workdir):
        first = get_encryption_key(PASSWORD, "salt.bin")
        assert (_workdir / "salt.bin").exists()

        second = get_encryption_key(PASSWORD, "salt.bin")

        assert first == second

    def test_existing_salt_file_is_used_as_is(self, _workdir):
        salt = b"fixed-salt-12345"
        (_workdir / "salt.bin").write_bytes(salt)

        key = get_encryption_key(PASSWORD, "salt.bin")

        assert key == generate_key_from_password(PASSWORD, salt)


class TestKeyEncryptor:
    def test_round_trip(self):
        encryptor = KeyEncryptor(PASSWORD)

        token = encryptor.encrypt("secret-value")

        assert token != "secret-value"
        assert encryptor.decrypt(token) == "secret-value"

    def test_empty_input_returns_empty_output(self):
        encryptor = KeyEncryptor(PASSWORD)

        assert encryptor.encrypt("") == ""
        assert encryptor.decrypt("") == ""

    def test_corrupted_token_returns_empty_string(self):
        encryptor = KeyEncryptor(PASSWORD)

        assert encryptor.decrypt("not-a-token") == ""

    def test_token_from_another_password_cannot_be_read(self):
        writer = KeyEncryptor("password-one")
        reader = KeyEncryptor("password-two")

        token = writer.encrypt("payload")

        assert reader.decrypt(token) == ""

    def test_two_encryptions_differ_but_both_decrypt(self):
        encryptor = KeyEncryptor(PASSWORD)

        first = encryptor.encrypt("payload")
        second = encryptor.encrypt("payload")

        assert first != second
        assert encryptor.decrypt(first) == encryptor.decrypt(second) == "payload"


class TestHashing:
    def test_round_trip_verifies(self):
        stored = hash_data("hunter2")

        assert verify_hashed_data(stored, "hunter2") is True

    def test_wrong_value_does_not_verify(self):
        stored = hash_data("hunter2")

        assert verify_hashed_data(stored, "hunter3") is False

    def test_explicit_salt_is_embedded_in_the_output(self):
        stored = hash_data("value", salt="pepper")

        assert stored.startswith("pepper$")

    def test_malformed_hash_returns_false(self):
        assert verify_hashed_data("no-separator", "value") is False

    def test_empty_hash_returns_false(self):
        assert verify_hashed_data("", "value") is False

    def test_non_string_hash_returns_false(self):
        assert verify_hashed_data(123, "value") is False

    def test_two_hashes_of_the_same_value_differ(self):
        assert hash_data("value") != hash_data("value")


class TestPasswordResolution:
    def test_environment_variable_is_used_when_the_secret_file_is_absent(self, monkeypatch):
        monkeypatch.setenv("SECRET_ENCRYPTION_PASSWORD", "from-env")

        assert get_password_from_key_manager() == "from-env"

    def test_returns_none_when_nothing_is_configured(self, monkeypatch):
        monkeypatch.delenv("SECRET_ENCRYPTION_PASSWORD", raising=False)

        assert get_password_from_key_manager() is None

    def test_mounted_secret_wins_over_the_environment(self, monkeypatch):
        monkeypatch.setenv("SECRET_ENCRYPTION_PASSWORD", "from-env")
        monkeypatch.setattr(
            security.Path, "read_text", lambda self, encoding=None: "  from-file  \n"
        )

        assert get_password_from_key_manager() == "from-file"

    def test_empty_secret_file_falls_back_to_the_environment(self, monkeypatch):
        monkeypatch.setenv("SECRET_ENCRYPTION_PASSWORD", "from-env")
        monkeypatch.setattr(security.Path, "read_text", lambda self, encoding=None: "   \n")

        assert get_password_from_key_manager() == "from-env"

    def test_unreadable_secret_file_falls_back_to_the_environment(self, monkeypatch):
        monkeypatch.setenv("SECRET_ENCRYPTION_PASSWORD", "from-env")

        def _raise(self, encoding=None):
            raise OSError("permission denied")

        monkeypatch.setattr(security.Path, "read_text", _raise)

        assert get_password_from_key_manager() == "from-env"
