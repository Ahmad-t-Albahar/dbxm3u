import unittest

from onboarding_logic import validate_access_token


class _FakeName:
    def __init__(self, display_name):
        self.display_name = display_name


class _FakeAccount:
    def __init__(self, display_name):
        self.name = _FakeName(display_name)


class _OkClient:
    def __init__(self, display_name):
        self._display_name = display_name

    def users_get_current_account(self):
        return _FakeAccount(self._display_name)


class _ErrClient:
    def __init__(self, exc: Exception):
        self._exc = exc

    def users_get_current_account(self):
        raise self._exc


class _Factory:
    def __init__(self, client):
        self._client = client
        self.last_token = None

    def from_access_token(self, token: str):
        self.last_token = token
        return self._client


class ValidateAccessTokenTests(unittest.TestCase):
    def test_empty_token(self):
        factory = _Factory(_OkClient("X"))
        res = validate_access_token("", factory)
        self.assertFalse(res.ok)
        self.assertIn("required", res.error_message.lower())

    def test_ok(self):
        factory = _Factory(_OkClient("John Doe"))
        res = validate_access_token("  abc  ", factory)
        self.assertTrue(res.ok)
        self.assertEqual(res.account_display_name, "John Doe")
        self.assertEqual(factory.last_token, "abc")

    def test_error(self):
        factory = _Factory(_ErrClient(RuntimeError("bad token")))
        res = validate_access_token("abc", factory)
        self.assertFalse(res.ok)
        self.assertIn("failed", res.error_message.lower())
        self.assertIn("bad token", res.error_message.lower())


if __name__ == "__main__":
    unittest.main()
