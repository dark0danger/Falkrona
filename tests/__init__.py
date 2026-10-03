"""Test bootstrap for the source-layout BrandPilot package."""

from pathlib import Path
import sys


SOURCE = Path(__file__).resolve().parents[1] / "packages" / "brandpilot_core" / "src"
sys.path.insert(0, str(SOURCE))
