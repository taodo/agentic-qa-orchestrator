"""Per-app host dependency; no singleton or database session."""
from typing import Annotated
from fastapi import Depends, Request, Query
from qa_sentinel.application import QASentinelApplication


def get_application(request: Request) -> QASentinelApplication:
    return request.app.state.application


Application = Annotated[QASentinelApplication, Depends(get_application)]
CollectionLimit = Annotated[int, Query(ge=1, le=200)]
TimelineLimit = Annotated[int, Query(ge=1, le=500)]
