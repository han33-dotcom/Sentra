"""Community Cloud entrypoint; repository root source package stays reviewable."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sentra.viewer_app import main

main()
