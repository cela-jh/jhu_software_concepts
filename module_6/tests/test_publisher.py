"""
`test_publisher.py`
Verifies publisher.py using a mocked pika so the tests never need a
live RabbitMQ broker.
"""
import json
import pytest
from unittest.mock import MagicMock, patch, call

import publisher


def _make_mock_channel():
    """Return a (mock_conn, mock_channel) pair wired up as pika would."""
    ch = MagicMock()
    conn = MagicMock()
    conn.channel.return_value = ch
    return conn, ch


@pytest.mark.integration
def test_constants_defined():
    """EXCHANGE, QUEUE, and ROUTING_KEY must be present and non-empty."""
    assert publisher.EXCHANGE
    assert publisher.QUEUE
    assert publisher.ROUTING_KEY


@pytest.mark.integration
def test_open_channel_declares_durable_exchange_queue_and_binding(monkeypatch):
    """_open_channel must declare a durable direct exchange, a durable
    queue, and bind them with the routing key."""
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    conn, ch = _make_mock_channel()
    with patch("publisher.pika.BlockingConnection", return_value=conn), \
         patch("publisher.pika.URLParameters"):
        result_conn, result_ch = publisher._open_channel()

    ch.exchange_declare.assert_called_once_with(
        exchange=publisher.EXCHANGE, exchange_type="direct", durable=True
    )
    ch.queue_declare.assert_called_once_with(queue=publisher.QUEUE, durable=True)
    ch.queue_bind.assert_called_once_with(
        exchange=publisher.EXCHANGE,
        queue=publisher.QUEUE,
        routing_key=publisher.ROUTING_KEY,
    )
    assert result_conn is conn
    assert result_ch is ch


@pytest.mark.integration
def test_publish_task_sends_persistent_message(monkeypatch):
    """publish_task must send delivery_mode=2 (persistent) to the exchange."""
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    conn, ch = _make_mock_channel()
    with patch("publisher.pika.BlockingConnection", return_value=conn), \
         patch("publisher.pika.URLParameters"), \
         patch("publisher.pika.BasicProperties") as mock_props:
        publisher.publish_task("scrape_new_data")

    mock_props.assert_called_once_with(delivery_mode=2, headers={})
    ch.basic_publish.assert_called_once()
    _, kwargs = ch.basic_publish.call_args
    assert kwargs["exchange"] == publisher.EXCHANGE
    assert kwargs["routing_key"] == publisher.ROUTING_KEY


@pytest.mark.integration
def test_publish_task_body_contains_kind_and_payload(monkeypatch):
    """The message body must be valid JSON with the correct kind and payload."""
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    conn, ch = _make_mock_channel()
    with patch("publisher.pika.BlockingConnection", return_value=conn), \
         patch("publisher.pika.URLParameters"), \
         patch("publisher.pika.BasicProperties"):
        publisher.publish_task("recompute_analytics", payload={"key": "val"})

    _, kwargs = ch.basic_publish.call_args
    body = json.loads(kwargs["body"])
    assert body["kind"] == "recompute_analytics"
    assert body["payload"] == {"key": "val"}
    assert "ts" in body


@pytest.mark.integration
def test_publish_task_closes_connection_after_publish(monkeypatch):
    """publish_task must close the broker connection even on success."""
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    conn, ch = _make_mock_channel()
    with patch("publisher.pika.BlockingConnection", return_value=conn), \
         patch("publisher.pika.URLParameters"), \
         patch("publisher.pika.BasicProperties"):
        publisher.publish_task("scrape_new_data")

    conn.close.assert_called_once()


@pytest.mark.integration
def test_publish_task_closes_connection_when_publish_raises(monkeypatch):
    """publish_task must close the connection even when basic_publish raises."""
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    conn, ch = _make_mock_channel()
    ch.basic_publish.side_effect = RuntimeError("broker error")
    with patch("publisher.pika.BlockingConnection", return_value=conn), \
         patch("publisher.pika.URLParameters"), \
         patch("publisher.pika.BasicProperties"):
        with pytest.raises(RuntimeError):
            publisher.publish_task("scrape_new_data")

    conn.close.assert_called_once()
