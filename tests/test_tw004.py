from __future__ import annotations

from tests.conftest import analyze_tw004 as analyze_source
from tests.conftest import finding_codes


def test_flags_direct_widen_then_cast() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = [1, 2]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" in finding_codes(result)


def test_flags_two_step_widen_then_cast() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    source = [1, 2]",
            "    w: Any = source",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" in finding_codes(result)


def test_flags_object_annotation() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    w: object = {'a': 1}",
            "    return cast(dict[str, int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" in finding_codes(result)


def test_allows_cast_without_prior_widen() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    w = [1, 2]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" not in finding_codes(result)


def test_ignores_reassigned_binding() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    source = [1]",
            "    source = [2]",
            "    w: Any = source",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" not in finding_codes(result)


def test_ignores_non_literal_initial_value() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f(items):",
            "    w: Any = items",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" not in finding_codes(result)


def test_ignores_shadowed_any() -> None:
    text = "\n".join(
        [
            "from typing import cast",
            "def f():",
            "    Any = object",
            "    w: Any = [1]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" not in finding_codes(result)


def test_supports_set_literal() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = {1, 2}",
            "    return cast(set[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" in finding_codes(result)


def test_supports_tuple_literal() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = (1, 2)",
            "    return cast(tuple[int, ...], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" in finding_codes(result)


def test_does_not_cross_function_scope() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "source = [1]",
            "w: Any = source",
            "def f():",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" not in finding_codes(result)


def test_augassign_invalidates_widen_binding() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = [1]",
            "    w += [2]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" not in finding_codes(result)


def test_assign_unpack_invalidates_widen_binding() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = [1]",
            "    a = 0",
            "    a, w = 1, [2]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" not in finding_codes(result)


def test_augassign_attribute_does_not_invalidate_local() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    obj = object()",
            "    w: Any = [1]",
            "    obj.attr += 1",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" in finding_codes(result)


def test_augassign_subscript_does_not_invalidate_local() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    items = [1]",
            "    w: Any = [1]",
            "    items[0] += 1",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" in finding_codes(result)


def test_nonlocal_assignment_invalidates_outer_binding() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = [1]",
            "    def inner():",
            "        nonlocal w",
            "        w = [2]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" not in finding_codes(result)


def test_nonlocal_augassign_invalidates_outer_binding() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = [1]",
            "    def inner():",
            "        nonlocal w",
            "        w += [2]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" not in finding_codes(result)


def test_nonlocal_in_nested_control_flow_invalidates() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = [1]",
            "    def inner():",
            "        nonlocal w",
            "        if True:",
            "            w = [2]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" not in finding_codes(result)


def test_nested_read_only_does_not_invalidate_outer_binding() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "def f():",
            "    w: Any = [1]",
            "    def inner():",
            "        return w",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" in finding_codes(result)


def test_global_does_not_invalidate_outer_local() -> None:
    text = "\n".join(
        [
            "from typing import Any, cast",
            "w = None",
            "def f():",
            "    w: Any = [1]",
            "    def inner():",
            "        global w",
            "        w = [2]",
            "    return cast(list[int], w)  # SAFETY: narrow list",
        ]
    )
    result = analyze_source(text)
    assert "TW004" in finding_codes(result)
