import os
import json
from datetime import datetime
import hashlib

def save_all_project_code(root_path: str):
    ignore_dirs = {"__pycache__", "copyfile", "Main", ".git", ".github", ".vscode", "logs", "openspec"}
    ignore_files = {"__init__.py"}
    
    # Target project directories (exclude installed packages in Main/Lib/site-packages)
    target_dirs = {"app", "analysis", "backtesting", "common", "config", "data", 
                   "features", "modeling", "models", "services", "strategy", 
                   "utils", "scripts"}

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(script_dir, "full-trade.txt")
    
    file_metadata = []
    total_files = 0
    total_lines = 0
    total_chars = 0

    with open(output_file, "w", encoding="utf-8") as out:
        # Write header with metadata
        out.write(f"# YujTrade Project - Full Code Export\n")
        out.write(f"# Generated: {datetime.now().isoformat()}\n")
        out.write(f"# Root: {root_path}\n")
        out.write(f"# Format: Each file has metadata header + content\n")
        out.write(f"# Metadata: path, lines, chars, hash (first 8 chars of sha256)\n")
        out.write(f"{'='*80}\n\n")

        for target in target_dirs:
            target_path = os.path.join(root_path, target)
            if not os.path.exists(target_path):
                continue
                
            for folder, dirs, files in os.walk(target_path):
                # Skip ignored directories
                dirs[:] = [d for d in dirs if d not in ignore_dirs]
                
                # Filter Python files
                py_files = [f for f in files if f.endswith(".py") and f not in ignore_files]
                if not py_files:
                    continue

                for file in py_files:
                    file_path = os.path.join(folder, file)
                    relative_path = os.path.relpath(file_path, root_path)

                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                    except Exception as e:
                        content = f"--- Error reading file: {e} ---"

                    lines = content.count('\n') + 1
                    chars = len(content)
                    file_hash = hashlib.sha256(content.encode()).hexdigest()[:8]

                    # Metadata header for LLM efficiency
                    out.write(f"# FILE: {relative_path}\n")
                    out.write(f"# LINES: {lines} | CHARS: {chars} | HASH: {file_hash}\n")
                    out.write(f"{'-'*80}\n")
                    out.write(content)
                    out.write(f"\n{'='*80}\n\n")

                    file_metadata.append({
                        "path": relative_path,
                        "lines": lines,
                        "chars": chars,
                        "hash": file_hash
                    })
                    total_files += 1
                    total_lines += lines
                    total_chars += chars

        # Also include root-level main.py if exists
        root_main = os.path.join(root_path, "main.py")
        if os.path.exists(root_main):
            relative_path = "main.py"
            try:
                with open(root_main, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                content = f"--- Error reading file: {e} ---"
            
            lines = content.count('\n') + 1
            chars = len(content)
            file_hash = hashlib.sha256(content.encode()).hexdigest()[:8]

            out.write(f"# FILE: {relative_path}\n")
            out.write(f"# LINES: {lines} | CHARS: {chars} | HASH: {file_hash}\n")
            out.write(f"{'-'*80}\n")
            out.write(content)
            out.write(f"\n{'='*80}\n\n")

            file_metadata.append({
                "path": relative_path,
                "lines": lines,
                "chars": chars,
                "hash": file_hash
            })
            total_files += 1
            total_lines += lines
            total_chars += chars

        # Write summary at the end for quick reference
        out.write(f"\n{'='*80}\n")
        out.write(f"# SUMMARY\n")
        out.write(f"# Total files: {total_files}\n")
        out.write(f"# Total lines: {total_lines}\n")
        out.write(f"# Total chars: {total_chars}\n")
        out.write(f"# Generated: {datetime.now().isoformat()}\n")
        out.write(f"{'='*80}\n")
        
        # Write file index for quick navigation
        out.write(f"\n# FILE INDEX (for quick navigation)\n")
        for meta in file_metadata:
            out.write(f"# {meta['path']} | L:{meta['lines']} C:{meta['chars']} H:{meta['hash']}\n")

    print(f"[OK] Saved: full-trade.txt")
    print(f"[INFO] Total files: {total_files}")
    print(f"[INFO] Total lines: {total_lines}")
    print(f"[INFO] Total chars: {total_chars}")
    print(f"[INFO] Output: {output_file}")


if __name__ == "__main__":
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    save_all_project_code(project_path)