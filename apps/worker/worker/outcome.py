"""What a job reports to the dispatcher; the outcome itself is recorded on the job's row."""

from typing import Literal

Outcome = Literal["done", "failed", "skipped"]
