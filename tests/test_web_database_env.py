from web import database_url_from_env


def test_database_url_empty_uses_fallback() -> None:
    assert database_url_from_env({
        "DATABASE_URL": "",
        "STAXIS_DATABASE_URL": "sqlite:///fallback.db",
    }) == "sqlite:///fallback.db"


def test_database_url_whitespace_uses_fallback() -> None:
    assert database_url_from_env({
        "DATABASE_URL": "   ",
        "STAXIS_DATABASE_URL": "sqlite:///fallback.db",
    }) == "sqlite:///fallback.db"


def test_database_url_empty_without_fallback_uses_default() -> None:
    assert database_url_from_env({"DATABASE_URL": "", "STAXIS_DATABASE_URL": ""}) == "sqlite:///stataxis.db"
