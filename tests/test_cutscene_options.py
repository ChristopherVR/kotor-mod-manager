from installer.cutscene_options import prepare_cutscenes


def _files(root, names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())


def test_subtitle_choice_applies_to_all_movies_and_keeps_unique_files(tmp_path):
    _files(tmp_path, ["movies/a.bik", "movies/b.bik", "movies/c.bik",
                      "alts/nosubs/a.bik", "alts/nosubs/b.bik",
                      "alts/whitesubs/a.bik", "alts/whitesubs/b.bik"])
    asked = []
    def ask(title, body, options):
        asked.append(options)
        return "alts/whitesubs"
    plan = prepare_cutscenes([(tmp_path, False)], ask)
    assert len(asked) == 1
    assert {m.source.relative_to(tmp_path).as_posix() for m in plan.file_mappings} == {
        "alts/whitesubs/a.bik", "alts/whitesubs/b.bik", "movies/c.bik"}
    assert all(m.dest_relative.startswith("Movies/") for m in plan.file_mappings)


def test_subtitles_and_legal_screen_are_separate_choices(tmp_path):
    _files(tmp_path, ["movies/a.bik", "nosubs/a.bik", "tex/legal.tga", "legal/legal.tga"])
    plan = prepare_cutscenes([(tmp_path, False)],
                            lambda title, body, options: "nosubs" if "nosubs" in options else "tex")
    assert {m.dest_relative for m in plan.file_mappings} == {"Movies/a.bik", "Override/legal.tga"}


def test_skip_aborts_entire_selection_before_install(tmp_path):
    _files(tmp_path, ["a.bik", "nosubs/a.bik"])
    assert prepare_cutscenes([(tmp_path, False)], lambda *a: "skip") is None


def test_only_selected_mod_movies_replace_main_movies(tmp_path):
    main, addons = tmp_path / "main", tmp_path / "addons"
    _files(main, ["a.bik", "b.bik"])
    _files(addons, ["mods/TSLRCM/a.bik", "mods/Extended Enclave/b.bik", "mods/M4-78/c.bik"])
    asked = []
    def ask(title, body, options):
        asked.append(title)
        return "Install these cutscenes" if "TSLRCM" in title else "Leave these out"
    plan = prepare_cutscenes([(main, False), (addons, True)], ask)
    sources = {m.dest_relative: m.source for m in plan.file_mappings}
    assert len(asked) == 3
    assert sources == {"Movies/a.bik": addons / "mods/TSLRCM/a.bik", "Movies/b.bik": main / "b.bik"}


def test_pipeline_installs_selected_style_and_leaves_other_styles_out(tmp_path):
    import zipfile
    from tests.test_pipeline_fixes import _mod, _pipeline
    mod = _mod(file_id="2380", name="K1 Cutscenes Rescaled")
    p = _pipeline(tmp_path, [mod])
    p._game_path.mkdir()
    archive = tmp_path / "k1rs_30fps_1920x1080.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("movies/a.bik", b"base")
        z.writestr("nosubs/a.bik", b"chosen")
        z.writestr("whitesubs/a.bik", b"other")
        z.writestr("movies/b.bik", b"unchanged")
    p.confirm = lambda title, body, options: "nosubs"
    pm = p.mods[0]
    pm.archive_paths = [archive]
    p._extract_and_install(pm)
    assert pm.status.name == "DONE", pm.error
    assert (p._game_path / "Movies/a.bik").read_bytes() == b"chosen"
    assert (p._game_path / "Movies/b.bik").read_bytes() == b"unchanged"
    assert not (p._game_path / "Override/a.bik").exists()


def test_pipeline_skipping_style_does_not_write_any_game_files(tmp_path):
    import zipfile
    from tests.test_pipeline_fixes import _mod, _pipeline
    p = _pipeline(tmp_path, [_mod(file_id="2380")])
    p._game_path.mkdir()
    archive = tmp_path / "cutscenes.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("movies/a.bik", b"base")
        z.writestr("nosubs/a.bik", b"alt")
    p.confirm = lambda *a: "skip"
    pm = p.mods[0]
    pm.archive_paths = [archive]
    p._extract_and_install(pm)
    assert pm.status.name == "SKIPPED"
    assert list(p._game_path.iterdir()) == []
