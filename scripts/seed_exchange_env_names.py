import io
from pathlib import Path

from trading.exchanges.registry import all_secret_names

env_path = Path(".env")
text = env_path.read_text(encoding="utf-8")
lines = text.splitlines()
existing = {line.split("=", 1)[0].strip() for line in lines if "=" in line}
names = list(all_secret_names())
missing = [name for name in names if name not in existing and f"ENCRYPTED_{name}" not in existing]
if missing:
    buffer = io.StringIO()
    if lines and lines[-1].strip():
        buffer.write("\n")
    buffer.write("# Exchange API key names (values are filled by the operator)\n")
    for name in missing:
        buffer.write(f"{name}=\n")
    with env_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(buffer.getvalue())
print(f"added {len(missing)} names")
