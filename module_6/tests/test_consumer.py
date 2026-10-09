"""
`test_consumer.py`
Unit tests for the RabbitMQ consumer. All broker and DB interactions
are mocked so these tests never need a running RabbitMQ or PostgreSQL.
"""
import json
import pytest
from unittest.mock import MagicMock, patch

import consumer


def _make_delivery(tag=1):
    """Return a mock pika method frame with the given delivery tag."""
    method = MagicMock()
    method.delivery_tag = tag
    return method


# ---- handler unit tests ----

@pytest.mark.integration
def test_handle_scrape_new_data_passes_since_from_payload():
    """handle_scrape_new_data must forward payload['since'] to load_incremental."""
    conn = MagicMock()
    with patch("consumer.load_incremental", return_value=3) as mock_load:
        consumer.handle_scrape_new_data(conn, {"since": "100"})
    mock_load.assert_called_once_with(conn, consumer.SEED_JSON, since="100")


@pytest.mark.integration
def test_handle_scrape_new_data_uses_none_when_since_absent():
    """handle_scrape_new_data passes since=None when the payload omits it,
    so load_incremental falls back to the stored watermark."""
    conn = MagicMock()
    with patch("consumer.load_incremental", return_value=0) as mock_load:
        consumer.handle_scrape_new_data(conn, {})
    mock_load.assert_called_once_with(conn, consumer.SEED_JSON, since=None)


@pytest.mark.integration
def test_handle_recompute_analytics_delegates_to_run_analytics():
    """handle_recompute_analytics must call run_analytics with the connection."""
    conn = MagicMock()
    with patch("consumer.run_analytics") as mock_run:
        consumer.handle_recompute_analytics(conn, {})
    mock_run.assert_called_once_with(conn)


# ---- _on_message routing and ack/nack ----

@pytest.mark.integration
def test_on_message_acks_and_commits_on_success():
    """A valid known-kind message must trigger the handler, commit, and ack."""
    ch = MagicMock()
    method = _make_delivery(tag=42)
    conn = MagicMock()
    body = json.dumps({"kind": "scrape_new_data", "payload": {}}).encode()

    with patch("consumer.load_incremental", return_value=0):
        consumer._on_message(ch, method, None, body, conn)

    conn.commit.assert_called_once()
    ch.basic_ack.assert_called_once_with(delivery_tag=42)
    ch.basic_nack.assert_not_called()


@pytest.mark.integration
def test_on_message_nacks_malformed_json_without_committing():
    """A non-JSON body must be discarded with a nack; no commit or rollback."""
    ch = MagicMock()
    method = _make_delivery(tag=1)
    conn = MagicMock()

    consumer._on_message(ch, method, None, b"not-json{{", conn)

    ch.basic_nack.assert_called_once_with(delivery_tag=1, requeue=False)
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()


@pytest.mark.integration
def test_on_message_nacks_unknown_kind():
    """An unknown kind must be discarded with nack(requeue=False)."""
    ch = MagicMock()
    method = _make_delivery(tag=2)
    conn = MagicMock()
    body = json.dumps({"kind": "nonexistent_task", "payload": {}}).encode()

    consumer._on_message(ch, method, None, body, conn)

    ch.basic_nack.assert_called_once_with(delivery_tag=2, requeue=False)
    ch.basic_ack.assert_not_called()


@pytest.mark.integration
def test_on_message_rolls_back_and_nacks_on_handler_error():
    """When the handler raises, the transaction must roll back and the
    delivery must be nacked without requeue."""
    ch = MagicMock()
    method = _make_delivery(tag=3)
    conn = MagicMock()
    body = json.dumps({"kind": "scrape_new_data", "payload": {}}).encode()

    with patch("consumer.load_incremental", side_effect=RuntimeError("disk full")):
        consumer._on_message(ch, method, None, body, conn)

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    ch.basic_nack.assert_called_once_with(delivery_tag=3, requeue=False)


# ---- main() lifecycle ----

@pytest.mark.integration
def test_main_starts_and_stops_on_keyboard_interrupt(monkeypatch):
    """main() must call start_consuming and stop gracefully on Ctrl-C,
    closing both DB and broker connections in its finally block."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/test")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

    mock_db_conn = MagicMock()
    mock_ch = MagicMock()
    mock_mq_conn = MagicMock()
    mock_mq_conn.channel.return_value = mock_ch
    mock_ch.start_consuming.side_effect = KeyboardInterrupt

    with patch("consumer.psycopg.connect", return_value=mock_db_conn), \
         patch("consumer.pika.BlockingConnection", return_value=mock_mq_conn):
        consumer.main()

    mock_ch.start_consuming.assert_called_once()
    mock_ch.stop_consuming.assert_called_once()
    mock_db_conn.close.assert_called_once()
    mock_mq_conn.close.assert_called_once()


@pytest.mark.integration
def test_main_declares_durable_amqp_entities(monkeypatch):
    """main() must declare the exchange, queue, and binding as durable,
    then set prefetch_count=1 before consuming."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/test")
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")

    mock_db_conn = MagicMock()
    mock_ch = MagicMock()
    mock_mq_conn = MagicMock()
    mock_mq_conn.channel.return_value = mock_ch
    mock_ch.start_consuming.side_effect = KeyboardInterrupt

    with patch("consumer.psycopg.connect", return_value=mock_db_conn), \
         patch("consumer.pika.BlockingConnection", return_value=mock_mq_conn):
        consumer.main()

    mock_ch.exchange_declare.assert_called_once_with(
        exchange=consumer.EXCHANGE, exchange_type="direct", durable=True
    )
    mock_ch.queue_declare.assert_called_once_with(queue=consumer.QUEUE, durable=True)
    mock_ch.queue_bind.assert_called_once_with(
        exchange=consumer.EXCHANGE,
        queue=consumer.QUEUE,
        routing_key=consumer.ROUTING_KEY,
    )
    mock_ch.basic_qos.assert_called_once_with(prefetch_count=1)
