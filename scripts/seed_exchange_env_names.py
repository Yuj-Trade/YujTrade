import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.logger import logger
from trading.exchanges.registry import all_secret_names

env_path = Path(".env")
names: list[str] = []


def main() -> None:
    path = env_path
    if not path.exists():
        logger.error(f"{path} does not exist; create it first.")
        return
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    existing = {line.split("=", 1)[0].strip() for line in lines if "=" in line}
    wanted = names or list(all_secret_names())
    missing = [
        name for name in wanted if name not in existing and f"ENCRYPTED_{name}" not in existing
    ]
    if not missing:
        logger.info("No exchange key names are missing.")
        return
    buffer = io.StringIO()
    if lines and lines[-1].strip():
        buffer.write("\n")
    buffer.write("# Exchange API key names. Values are filled and encrypted by the operator.\n")
    for name in missing:
        buffer.write(f"{name}=\n")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(buffer.getvalue())
    logger.info(f"Added {len(missing)} exchange key names with empty values.")


if __name__ == "__main__":
    main()
