"""The fixes applied to the pinned HoloPatcher source before it is built."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("setup_holopatcher", ROOT / "tools" / "setup_holopatcher.py")
hp = importlib.util.module_from_spec(spec)
sys.modules["setup_holopatcher"] = hp
spec.loader.exec_module(hp)

ORIGINAL = """import ctypes
import json
import tkinter as tk

ctypes.windll.shcore.SetProcessDpiAwareness(True)  # noqa: FBT003

file_path = None
"""


def _tree(tmp_path, text=ORIGINAL):
    """A fake PyKotor checkout holding every file the build patches."""
    f = tmp_path / "Libraries/Utility/src/utility/tkinter/rte_editor.py"
    f.parent.mkdir(parents=True)
    f.write_text(text, encoding="utf-8")
    lexer = tmp_path / "Libraries/PyKotor/src/pykotor/resource/formats/ncs/compiler/lexer.py"
    lexer.parent.mkdir(parents=True)
    lexer.write_text(LEXER, encoding="utf-8")
    return f


def test_the_windows_only_call_is_guarded(tmp_path):
    f = _tree(tmp_path)
    assert hp._apply_source_patches(tmp_path)
    text = f.read_text()
    assert 'if os.name == "nt":\n    ctypes.windll.shcore' in text
    assert "import os\n" in text


def test_the_patched_module_imports_where_windll_does_not_exist(tmp_path, monkeypatch):
    """The real symptom: importing the module raised AttributeError off Windows."""
    f = _tree(tmp_path)
    hp._apply_source_patches(tmp_path)
    import types
    fake = types.ModuleType("tkinter")
    monkeypatch.setitem(sys.modules, "tkinter", fake)
    ns = {"__name__": "rte_editor"}
    code = f.read_text().replace("import tkinter as tk\n", "")
    exec(compile(code, str(f), "exec"), ns)               # must not raise


def test_applying_twice_is_fine(tmp_path):
    f = _tree(tmp_path)
    assert hp._apply_source_patches(tmp_path)
    once = f.read_text()
    assert hp._apply_source_patches(tmp_path)
    assert f.read_text() == once


def test_upstream_changing_stops_the_build_instead_of_shipping_unpatched(tmp_path, capsys):
    _tree(tmp_path, "import ctypes\nimport json\n# upstream rewrote this file\n")
    assert hp._apply_source_patches(tmp_path) is False
    assert "review SOURCE_PATCHES" in capsys.readouterr().out


LEXER = """class L:
    def t_INT_HEX_VALUE(self, t):
        "0x[0-9a-fA-F]+"  # noqa: D300, D400, D415
        t.value = IntExpression(int(t.value, 16))
        return t

MAPPINGS = \"\"\"
BinaryOperatorMapping(NCSInstructionType.ADDIF, DataType.INT, DataType.INT, DataType.FLOAT),
BinaryOperatorMapping(NCSInstructionType.ADDFI, DataType.FLOAT, DataType.FLOAT, DataType.INT),
BinaryOperatorMapping(NCSInstructionType.SUBIF, DataType.INT, DataType.INT, DataType.FLOAT),
BinaryOperatorMapping(NCSInstructionType.MULIF, DataType.INT, DataType.INT, DataType.FLOAT),
BinaryOperatorMapping(NCSInstructionType.MULFI, DataType.FLOAT, DataType.FLOAT, DataType.INT),
BinaryOperatorMapping(NCSInstructionType.DIVIF, DataType.INT, DataType.INT, DataType.FLOAT),
\"\"\"
"""


def _lexer_tree(tmp_path):
    _tree(tmp_path)
    return tmp_path / "Libraries/PyKotor/src/pykotor/resource/formats/ncs/compiler/lexer.py"


def _run_hex_rule(tmp_path, literal):
    f = _lexer_tree(tmp_path)
    assert hp._apply_source_patches(tmp_path)
    ns = {"IntExpression": lambda v: v}

    class T:
        value = literal

    exec(compile(f.read_text(), str(f), "exec"), ns)
    return ns["L"]().t_INT_HEX_VALUE(T()).value


def test_hex_literals_wrap_to_32_bit_signed_like_the_game_compiler(tmp_path):
    assert _run_hex_rule(tmp_path, "0xFFFFFFFF") == -1
    assert _run_hex_rule(tmp_path / "b", "0x80000000") == -2147483648


def test_hex_literals_that_already_fit_are_unchanged(tmp_path):
    assert _run_hex_rule(tmp_path, "0x7FFFFFFF") == 2147483647
    assert _run_hex_rule(tmp_path / "b", "0x7F000000") == 0x7F000000    # OBJECT_INVALID


def test_an_int_combined_with_a_float_is_typed_as_a_float(tmp_path):
    """FloatToInt(50 * fModifier) is valid NWScript: int * float is a float."""
    f = _lexer_tree(tmp_path)
    assert hp._apply_source_patches(tmp_path)
    text = f.read_text()
    for op in ("ADD", "SUB", "MUL", "DIV"):
        assert f"NCSInstructionType.{op}IF, DataType.FLOAT, DataType.INT, DataType.FLOAT" in text
        assert f"NCSInstructionType.{op}IF, DataType.INT, DataType.INT, DataType.FLOAT" not in text


def test_the_float_first_forms_were_already_right_and_are_left_alone(tmp_path):
    f = _lexer_tree(tmp_path)
    hp._apply_source_patches(tmp_path)
    text = f.read_text()
    assert "NCSInstructionType.MULFI, DataType.FLOAT, DataType.FLOAT, DataType.INT" in text
    assert "NCSInstructionType.ADDFI, DataType.FLOAT, DataType.FLOAT, DataType.INT" in text
