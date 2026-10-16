from fastapi import APIRouter

from app.dependencies import AdminOnly, AnyUser, not_implemented

router = APIRouter(tags=["sources"])


@router.post("/sources", dependencies=[AdminOnly])
def create_source():
    not_implemented()


@router.get("/sources", dependencies=[AnyUser])
def list_sources():
    not_implemented()


@router.delete("/sources/{source_id}", dependencies=[AdminOnly])
def delete_source(source_id: int):
    not_implemented()


@router.post("/samples", dependencies=[AdminOnly])
def create_samples():
    not_implemented()
