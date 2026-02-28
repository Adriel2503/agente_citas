"""
Punto de entrada para el agente de citas.
Ejecutar desde la raíz de agent_citas: python run.py
"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent
_src = _root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

if __name__ == "__main__":
    import runpy
    runpy.run_path(str(_src / "citas" / "main.py"), run_name="__main__")
