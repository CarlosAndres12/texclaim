"""Regenerate examples/word/paper.docx from examples/src/word_source.md (needs pandoc)."""

import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).parent


def main() -> None:
    if not shutil.which("pandoc"):
        raise SystemExit("pandoc is required")
    src = HERE / "src" / "word_source.md"
    out = HERE / "word" / "paper.docx"
    subprocess.run(["pandoc", str(src), "-o", str(out)], check=True)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
