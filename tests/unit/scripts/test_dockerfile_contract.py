from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_the_image_asserts_ccxt_imports_at_build_time():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "import ccxt" in dockerfile
    install = dockerfile.index("pip install")
    assertion = dockerfile.index("import ccxt")
    assert install < assertion, "the ccxt import check must run after the install"


def test_the_image_installs_the_manifest():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "pip install --no-cache-dir -r requirements.txt" in dockerfile


def test_the_image_runs_as_a_non_root_user():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "USER appuser" in dockerfile
    assert "root" not in dockerfile.split("USER appuser")[1]
