import sys
from pathlib import Path

# src layout: 'src' klasörünü import path'e ekle
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from testmaker.app import main

if __name__ == "__main__":
    raise SystemExit(main())
