"""Library API route wiring.

The bulk endpoints live under /library/bulk/..., which collides with the
parameterised /library/{mod_id}/... routes. FastAPI matches in declaration
order, so if the parameterised one is declared first a request to
/library/bulk/uninstall binds mod_id="bulk" and fails with "Mod bulk not
found" - the handler is never reached. That is exactly what shipped, so the
ordering is pinned here rather than left to whoever edits the file next.
"""

from backend.library_routes import library_router


def _paths_in_order() -> list[str]:
    return [r.path for r in library_router.routes if hasattr(r, "path")]


def _index_of(path: str) -> int:
    paths = _paths_in_order()
    assert path in paths, f"{path} is not registered"
    return paths.index(path)


def test_bulk_routes_are_declared_before_the_mod_id_routes():
    """Literal segments must win over the {mod_id} placeholder."""
    for bulk in ("/api/library/bulk/uninstall", "/api/library/bulk/toggle"):
        assert _index_of(bulk) < _index_of("/api/library/{mod_id}/uninstall"), (
            f"{bulk} is shadowed by /library/{{mod_id}}/uninstall; "
            f"move it above the parameterised routes"
        )


def test_the_bulk_endpoints_are_registered():
    paths = _paths_in_order()
    assert "/api/library/bulk/uninstall" in paths
    assert "/api/library/bulk/toggle" in paths
    assert "/api/conflicts/resolve" in paths


def test_no_literal_library_route_is_shadowed_by_the_placeholder():
    """
    General guard for routes added later.

    A literal route only collides with a placeholder one when they have the
    same shape AND the same trailing segment: /library/bulk/uninstall clashes
    with /library/{mod_id}/uninstall, but not with
    /library/{mod_id}/open-folder. Comparing whole paths would flag harmless
    pairs, so match on the suffix.
    """
    paths = _paths_in_order()
    placeholder_at: dict[str, int] = {}
    for i, p in enumerate(paths):
        if p.startswith("/api/library/{mod_id}/"):
            placeholder_at.setdefault(p.rsplit("/", 1)[-1], i)

    shadowed = [
        p for i, p in enumerate(paths)
        if p.startswith("/api/library/")
        and not p.startswith("/api/library/{")
        and p.count("/") > 3
        and i > placeholder_at.get(p.rsplit("/", 1)[-1], len(paths))
    ]
    assert shadowed == [], (
        f"these are declared after a /library/{{mod_id}}/... route with the "
        f"same suffix, so they will never be reached: {shadowed}"
    )
