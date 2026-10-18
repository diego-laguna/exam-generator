from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends

Clock = Callable[[], datetime]


def get_clock() -> Clock:
    """Server clock (UTC). Overridden in tests to control time."""
    return lambda: datetime.now(UTC)


ClockDep = Annotated[Clock, Depends(get_clock)]
