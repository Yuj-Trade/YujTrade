import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load(script_name: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "scripts" / script_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docker_healthcheck_main_prints_healthy(capsys):
    module = load("docker_healthcheck.py", "docker_healthcheck")
    code = module.main()
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == "healthy"


def test_docker_healthcheck_main_is_idempotent():
    module = load("docker_healthcheck.py", "docker_healthcheck_2")
    assert module.main() == 0
