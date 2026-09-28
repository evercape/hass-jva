from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "jva_electric_fence"
LIBRARY = ("__init__.py", "client.py", "parser.py", "models.py")


def test_hacs_bundle_matches_library():
    src = ROOT / "src" / "jva_fence"
    bundled = COMPONENT / "bundled" / "jva_fence"
    for name in LIBRARY:
        assert (src / name).read_bytes() == (bundled / name).read_bytes(), name


def test_integration_does_not_submit_the_setup_form():
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in COMPONENT.rglob("*.py")
        if "bundled" not in path.parts
    )
    assert ".post(" not in text
    assert "admin/index.htm" not in text
