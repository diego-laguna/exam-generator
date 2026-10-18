"""Every route must be behind authentication unless explicitly listed as public."""

from fastapi.routing import APIRoute

from app.dependencies import get_current_claims
from app.main import app

PUBLIC = {
    "/health",
    "/api/v1/health",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
}


def _calls(dependant):
    yield dependant.call
    for sub in dependant.dependencies:
        yield from _calls(sub)


def test_every_route_requires_auth_unless_public():
    unguarded = [
        f"{sorted(route.methods or [])} {route.path}"
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path not in PUBLIC
        and get_current_claims not in set(_calls(route.dependant))
    ]
    assert not unguarded, f"Routes without an auth dependency: {unguarded}"
