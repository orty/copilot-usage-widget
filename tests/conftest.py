"""Mock GUI modules before widget.pyw is imported to prevent display initialization."""
import sys
import importlib.util
import pathlib
from unittest.mock import MagicMock

for _mod in [
    "tkinter", "tkinter.ttk", "tkinter.font",
    "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageTk", "PIL.ImageFilter",
]:
    sys.modules[_mod] = MagicMock()

import pytest

_WIDGET_PATH = pathlib.Path(__file__).parent.parent / "src" / "widget.pyw"


@pytest.fixture(scope="session")
def W():
    """Load widget.pyw as a module (GUI mocked). All tests use this fixture."""
    spec = importlib.util.spec_from_file_location("widget", _WIDGET_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["widget"] = mod
    spec.loader.exec_module(mod)
    return mod
