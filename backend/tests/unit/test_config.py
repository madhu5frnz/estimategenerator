import pytest

from app.config import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # The form docker-compose.yml passes.
        ("http://localhost:3000", ["http://localhost:3000"]),
        ("http://a.example, http://b.example", ["http://a.example", "http://b.example"]),
        ('["http://c.example"]', ["http://c.example"]),
    ],
)
def test_cors_origins_from_environment(
    raw: str, expected: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("API_CORS_ORIGINS", raw)
    assert Settings().api_cors_origins == expected
