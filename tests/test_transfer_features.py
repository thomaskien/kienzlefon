from __future__ import annotations

from pathlib import Path

import pytest

from kienzlefon.transfer_features import DEFAULT_TRANSFER_FEATURES, resolve_transfer_features


def write_features(etc: Path, content: str) -> None:
    etc.mkdir(exist_ok=True)
    (etc / "features.conf").write_text(content, encoding="utf-8")


def test_defaults_for_empty_configuration(tmp_path: Path) -> None:
    write_features(tmp_path, "; intentionally empty\n")

    assert DEFAULT_TRANSFER_FEATURES == {
        "atxfer": "*2",
        "atxferabort": "*1",
        "atxfercomplete": "*2",
    }
    assert resolve_transfer_features(tmp_path) == DEFAULT_TRANSFER_FEATURES


def test_preserves_explicit_codes_exactly(tmp_path: Path) -> None:
    write_features(
        tmp_path,
        """
        [featuremap]
        atxfer => #78
        [general]
        atxferabort = 11#
        atxfercomplete = 22#
        atxferthreeway = 33#
        atxferswap = 44#
        """,
    )

    assert resolve_transfer_features(tmp_path) == {
        "atxfer": "#78",
        "atxferabort": "11#",
        "atxfercomplete": "22#",
    }


def test_empty_requested_values_are_planned_for_channel(tmp_path: Path) -> None:
    write_features(
        tmp_path,
        """
        [featuremap]
        atxfer =
        [general]
        atxferabort =
        atxfercomplete =
        """,
    )

    assert resolve_transfer_features(tmp_path) == DEFAULT_TRANSFER_FEATURES


def test_start_code_avoids_other_explicit_featuremap_code(tmp_path: Path) -> None:
    write_features(tmp_path, "[featuremap]\nblindxfer => *2\n")

    first = resolve_transfer_features(tmp_path)
    second = resolve_transfer_features(tmp_path)

    assert first == second
    assert first["atxfer"] == "*1"
    assert first["atxfer"] != "*2"


def test_applicationmap_codes_do_not_block_start_code(tmp_path: Path) -> None:
    write_features(
        tmp_path,
        """
        [applicationmap]
        zero => 0,self,NoOp
        star => *,self,NoOp
        hash => #,self,NoOp
        two => *2,self,NoOp
        """,
    )

    assert resolve_transfer_features(tmp_path)["atxfer"] == "*2"


def test_include_glob_and_continuation_sections(tmp_path: Path) -> None:
    snippets = tmp_path / "features.d"
    snippets.mkdir()
    (snippets / "10-map.conf").write_text(
        "[featuremap](+)\natxfer => #61 ; inline comment\n", encoding="utf-8"
    )
    (snippets / "20-general.conf").write_text(
        "[general](+)\natxferabort = #62\natxfercomplete = #63\n"
        "atxferthreeway = #64\natxferswap = #65\n",
        encoding="utf-8",
    )
    write_features(tmp_path, '#include "features.d/*.conf"\n')

    assert resolve_transfer_features(tmp_path) == {
        "atxfer": "#61",
        "atxferabort": "#62",
        "atxfercomplete": "#63",
    }


def test_absolute_include_is_supported(tmp_path: Path) -> None:
    included = tmp_path / "outside-name.conf"
    included.write_text("[featuremap]\natxfer = 765\n", encoding="utf-8")
    write_features(tmp_path, f'#include "{included}"\n')

    assert resolve_transfer_features(tmp_path)["atxfer"] == "765"


def test_missing_tryinclude_is_ignored(tmp_path: Path) -> None:
    write_features(tmp_path, '#tryinclude "missing/*.conf"\n')

    assert resolve_transfer_features(tmp_path) == DEFAULT_TRANSFER_FEATURES


def test_missing_required_include_is_rejected(tmp_path: Path) -> None:
    write_features(tmp_path, '#include "missing.conf"\n')

    with pytest.raises(ValueError, match="Pflicht-Include"):
        resolve_transfer_features(tmp_path)


def test_include_cycle_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "loop.conf").write_text('#include "features.conf"\n', encoding="utf-8")
    write_features(tmp_path, '#include "loop.conf"\n')

    with pytest.raises(ValueError, match="Zyklischer"):
        resolve_transfer_features(tmp_path)


def test_exec_is_never_run_and_is_rejected(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    write_features(tmp_path, f'#exec "touch {marker}"\n')

    with pytest.raises(ValueError, match="#exec"):
        resolve_transfer_features(tmp_path)
    assert not marker.exists()


@pytest.mark.parametrize("code", ["12A", "123456789", "* 2", "ä"])
def test_invalid_start_codes_are_rejected(tmp_path: Path, code: str) -> None:
    write_features(tmp_path, f"[featuremap]\natxfer = {code}\n")

    with pytest.raises(ValueError, match="1 bis 8"):
        resolve_transfer_features(tmp_path)


def test_invalid_foreign_featuremap_code_is_rejected(tmp_path: Path) -> None:
    write_features(tmp_path, "[featuremap]\nblindxfer = unsafe-value\n")

    with pytest.raises(ValueError, match="Featurecode"):
        resolve_transfer_features(tmp_path)


def test_missing_control_defaults_avoid_explicit_control_prefixes(tmp_path: Path) -> None:
    write_features(
        tmp_path,
        """
        [general]
        atxferthreeway = *1
        atxferswap = *2
        """,
    )

    result = resolve_transfer_features(tmp_path)

    assert result["atxferabort"] == "*3"
    assert result["atxfercomplete"] == "*4"


def test_available_control_default_is_reserved_before_fallback(tmp_path: Path) -> None:
    write_features(tmp_path, "[general]\natxferthreeway = *1\n")

    result = resolve_transfer_features(tmp_path)

    assert result["atxferabort"] == "*3"
    assert result["atxfercomplete"] == "*2"


def test_explicit_ambiguous_control_codes_are_rejected(tmp_path: Path) -> None:
    write_features(
        tmp_path,
        """
        [general]
        atxferabort = *1
        atxfercomplete = *12
        atxferthreeway = *3
        atxferswap = *4
        """,
    )

    with pytest.raises(ValueError, match="präfixmehrdeutig"):
        resolve_transfer_features(tmp_path)


def test_start_code_may_equal_control_code(tmp_path: Path) -> None:
    write_features(tmp_path, "[featuremap]\natxfer = *1\n")

    result = resolve_transfer_features(tmp_path)

    assert result["atxfer"] == result["atxferabort"] == "*1"


def test_later_included_assignment_wins(tmp_path: Path) -> None:
    (tmp_path / "override.conf").write_text(
        "[featuremap](+)\natxfer = #8\n", encoding="utf-8"
    )
    write_features(
        tmp_path,
        "[featuremap]\natxfer = #7\n#include \"override.conf\"\n",
    )

    assert resolve_transfer_features(tmp_path)["atxfer"] == "#8"


def test_unsupported_relevant_section_inheritance_is_rejected(tmp_path: Path) -> None:
    write_features(tmp_path, "[general](template)\natxferabort = #1\n")

    with pytest.raises(ValueError, match="Sektionsvererbung"):
        resolve_transfer_features(tmp_path)
