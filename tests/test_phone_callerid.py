import pytest

from kienzlefon import phone_callerid as caller


def test_render_preserves_other_sections_and_reconciles_inventory():
    main = '#include "phones.conf"\r\n[trunk]\r\ncallerid=External <555>\r\n'
    named = caller.render_names(main, {"201": 'Büro "A"; OG\\West', "202": "Links"})
    assert named.startswith(main)
    assert '[201](+type=endpoint)\ncallerid="Büro \\"A\\"\\; OG\\\\West" <201>\n' in named
    assert caller.render_names(named, {"203": "Rechts"}) == caller.render_names(main, {"203": "Rechts"})
    assert caller.render_names(named, {}) == main
    for invalid in ({"[201]": "Büro"}, {"201": "abc\n[trunk]"}, {"201": "ä" * 40}):
        with pytest.raises(ValueError):
            caller.render_names(main, invalid)
    with pytest.raises(ValueError):
        caller.render_names(main + caller.BEGIN + "\n", {"201": "A"})


@pytest.mark.parametrize("failure", ["confirmation", "saving"])
def test_failures_restore_the_pbx_file_and_reload(tmp_path, monkeypatch, failure):
    path = tmp_path / "pjsip.conf"
    path.write_text("; initial\n")
    loads = []

    def cli(command):
        if command == "pjsip reload":
            loads.append(path.read_text())
            return ""
        return 'callerid : "Büro" <201>' if failure == "saving" else 'callerid : "Alt" <201>'

    monkeypatch.setattr(caller, "_cli", cli)
    times = iter([0, 6])
    monkeypatch.setattr(caller.time, "monotonic", lambda: next(times))
    with pytest.raises(ValueError, match="nicht bestätigt" if failure == "confirmation" else "Schreibfehler"):
        with caller.apply_names(tmp_path, {"201": "Büro"}):
            assert failure == "saving"
            raise ValueError("Schreibfehler")
    assert len(loads) == 2
    assert loads[-1] == path.read_text() == "; initial\n"


def test_unchanged_names_skip_reload_but_correct_runtime_drift(tmp_path, monkeypatch):
    path = tmp_path / "pjsip.conf"
    names = {"201": "Links"}
    path.write_text(caller.render_names("", names))
    active = '"Alt" <201>'
    reloads = []

    def cli(command):
        nonlocal active
        if command == "pjsip reload":
            reloads.append(command)
            active = '"Links" <201>'
        return " callerid : " + active

    monkeypatch.setattr(caller, "_cli", cli)
    for _ in range(2):
        with caller.apply_names(tmp_path, names):
            assert active == '"Links" <201>'
    assert len(reloads) == 1
