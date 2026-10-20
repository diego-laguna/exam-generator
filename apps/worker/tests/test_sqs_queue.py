import boto3
from exam_core.queue import IngestDocument, Received, SqsQueue, decode


class FakeSqs:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.inbox = [{"ReceiptHandle": "rh", "Body": '{"type":"run_generation","job_id":9}'}]

    def send_message(self, **kw):
        self.calls.append(("send", kw))

    def receive_message(self, **kw):
        self.calls.append(("receive", kw))
        messages, self.inbox = self.inbox, []
        return {"Messages": messages} if messages else {}

    def delete_message(self, **kw):
        self.calls.append(("delete", kw))

    def change_message_visibility(self, **kw):
        self.calls.append(("extend", kw))


def make_queue(monkeypatch, endpoint=None):
    fake, made = FakeSqs(), {}

    def client(service, **kw):
        made.update(kw, service=service)
        return fake

    monkeypatch.setattr(boto3, "client", client)
    return SqsQueue("https://sqs.example/q", "eu-west-1", endpoint), fake, made


def test_send_receive_delete_and_extend(monkeypatch):
    queue, fake, made = make_queue(monkeypatch)
    queue.send(IngestDocument(document_id=5))
    assert fake.calls[0] == ("send", {"QueueUrl": "https://sqs.example/q", "MessageBody": '{"type":"ingest_document","document_id":5}'})
    got = queue.receive(20, 300)
    assert got == [Received("rh", '{"type":"run_generation","job_id":9}')] and decode(got[0].body).type == "run_generation"
    assert fake.calls[1][1] == {"QueueUrl": "https://sqs.example/q", "MaxNumberOfMessages": 1, "WaitTimeSeconds": 20, "VisibilityTimeout": 300}
    assert queue.receive(20, 300) == []  # an empty poll has no "Messages" key
    queue.extend("rh", 300)
    queue.delete("rh")
    assert [c[0] for c in fake.calls][-2:] == ["extend", "delete"]
    assert made == {"service": "sqs", "region_name": "eu-west-1"}


def test_local_emulator_gets_endpoint_and_dummy_credentials(monkeypatch):
    _, _, made = make_queue(monkeypatch, endpoint="http://localhost:9324")
    assert made["endpoint_url"] == "http://localhost:9324" and made["aws_access_key_id"] == "local"
