import pytest


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path_factory, monkeypatch):
    """Keep tests away from the real user config, cache and environment."""
    root = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("TEXCLAIM_CONFIG_DIR", str(root / "config"))
    monkeypatch.setenv("TEXCLAIM_CACHE_DIR", str(root / "cache"))
    for var in ("TEXCLAIM_MODEL", "OPENALEX_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def pytest_collection_modifyitems(config, items):
    import os

    if os.environ.get("TEXCLAIM_LIVE_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="set TEXCLAIM_LIVE_TESTS=1 to run live tests")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
