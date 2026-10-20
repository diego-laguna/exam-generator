"""Background-job queue: the API sends messages, the worker receives them (Amazon SQS).

A message only names the work (`ingest_document 12`); the state lives in Postgres. That keeps
messages tiny and makes redelivery safe: the worker claims the row, and a message whose row is
already done, failed or deleted is acknowledged and dropped.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, Field, TypeAdapter

from exam_core.config import get_settings


class IngestDocument(BaseModel):
    type: Literal["ingest_document"] = "ingest_document"
    document_id: int


class IngestSource(BaseModel):
    type: Literal["ingest_source"] = "ingest_source"
    source_id: int


class RunGeneration(BaseModel):
    type: Literal["run_generation"] = "run_generation"
    job_id: int


class EmbedSamples(BaseModel):
    type: Literal["embed_samples"] = "embed_samples"
    sample_ids: list[int]


Message = Annotated[
    IngestDocument | IngestSource | RunGeneration | EmbedSamples, Field(discriminator="type")
]
_message = TypeAdapter[Message](Message)


def encode(message: Message) -> str:
    return _message.dump_json(message).decode()


def decode(body: str) -> Message:
    """Raises pydantic.ValidationError for anything that is not a known message."""
    return _message.validate_json(body)


class Queue(Protocol):
    def send(self, message: Message) -> None: ...


@dataclass(frozen=True)
class Received:
    receipt: str
    body: str


class QueueNotConfigured(RuntimeError):
    pass


class SqsQueue:
    """Credentials come from the default AWS chain (the ECS task role on AWS)."""

    def __init__(self, queue_url: str, region: str, endpoint_url: str | None = None) -> None:
        import boto3

        self._url = queue_url
        if endpoint_url:  # a local emulator accepts any credentials
            self._client = boto3.client(
                "sqs",
                region_name=region,
                endpoint_url=endpoint_url,
                aws_access_key_id="local",
                aws_secret_access_key="local",
            )
        else:
            self._client = boto3.client("sqs", region_name=region)

    def send(self, message: Message) -> None:
        self._client.send_message(QueueUrl=self._url, MessageBody=encode(message))

    def receive(self, wait_seconds: int, visibility_seconds: int) -> list[Received]:
        response = self._client.receive_message(
            QueueUrl=self._url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=wait_seconds,
            VisibilityTimeout=visibility_seconds,
        )
        return [Received(m.get("ReceiptHandle", ""), m.get("Body", "")) for m in response.get("Messages", [])]

    def delete(self, receipt: str) -> None:
        self._client.delete_message(QueueUrl=self._url, ReceiptHandle=receipt)

    def extend(self, receipt: str, visibility_seconds: int) -> None:
        self._client.change_message_visibility(
            QueueUrl=self._url, ReceiptHandle=receipt, VisibilityTimeout=visibility_seconds
        )


@lru_cache
def get_sqs_queue() -> SqsQueue:
    settings = get_settings()
    if not settings.sqs_queue_url:
        raise QueueNotConfigured("SQS_QUEUE_URL is not set")
    return SqsQueue(settings.sqs_queue_url, settings.sqs_region, settings.sqs_endpoint_url)
