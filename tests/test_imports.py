"""Task 10: smoke-test that main_v2 imports cleanly and exposes `main`."""


def test_main_v2_imports():
    import main_v2
    assert hasattr(main_v2, "main"), "main_v2 must expose a `main` coroutine"
    assert callable(main_v2.main)
