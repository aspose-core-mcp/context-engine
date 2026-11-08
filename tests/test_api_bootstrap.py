from adcs.api.main import create_app


def test_api_bootstrap_has_root_route() -> None:
    app = create_app()

    # ``create_app`` mounts sub-routers via ``include_router``; on FastAPI 0.138
    # those become ``_IncludedRouter`` objects that do NOT expose ``.path``, so a
    # bare ``route.path`` comprehension raises ``AttributeError``. The root ``/``
    # route is a direct ``@app.get("/")`` (a real ``APIRoute`` with ``.path``), so
    # we only introspect routes that actually carry a path.
    route_paths = {route.path for route in app.router.routes if hasattr(route, "path")}
    assert "/" in route_paths
    assert hasattr(app.state, "translation_fallback_service")
