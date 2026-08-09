from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from re import Pattern


def _patterns() -> tuple[Pattern[str], ...]:
    root = Path(__file__).resolve().parents[2]
    spec = spec_from_file_location("pat_secret_scan", root / "scripts" / "secret_scan.py")
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._TOKEN_PATTERNS  # type: ignore[attr-defined, no-any-return]


def test_secret_patterns_reject_css_class_false_positive() -> None:
    patterns = _patterns()
    assert not any(pattern.search(".sk-toggleable__label-arrow") for pattern in patterns)


def test_secret_patterns_detect_supported_openai_key_shapes() -> None:
    patterns = _patterns()
    examples = (
        "sk-" + "A1" * 12,
        "sk-proj-" + "A1_" * 10,
        "sk-svcacct-" + "Z9-" * 10,
    )
    assert all(any(pattern.search(value) for pattern in patterns) for value in examples)
