"""
`publisher.py`
RabbitMQ publisher for the web service. Enqueues tasks to be processed
asynchronously by the worker.
"""
import json
import os
from datetime import datetime, timezone

import pika

# Exchange, queue, and routing key constants shared by publisher and consumer.
EXCHANGE = "tasks"
QUEUE = "tasks_q"
ROUTING_KEY = "tasks"


def _open_channel():
    """
    Open a RabbitMQ connection and channel, declaring the durable
    exchange, queue, and binding idempotently.

    :returns: An open (connection, channel) pair. The caller must close
        the connection when done.
    :rtype: tuple(pika.BlockingConnection, pika.channel.Channel)
    """
    url = os.environ["RABBITMQ_URL"]
    params = pika.URLParameters(url)
    conn = pika.BlockingConnection(params)
    ch = conn.channel()
    ch.exchange_declare(exchange=EXCHANGE, exchange_type="direct", durable=True)
    ch.queue_declare(queue=QUEUE, durable=True)
    ch.queue_bind(exchange=EXCHANGE, queue=QUEUE, routing_key=ROUTING_KEY)
    return conn, ch


def publish_task(kind: str, payload: dict | None = None,
                 headers: dict | None = None) -> None:
    """
    Publish a task message to the tasks exchange. The message body is
    compact JSON containing ``kind``, a UTC ISO timestamp (``ts``), and
    ``payload``. Messages are persisted with ``delivery_mode=2``.

    :param kind: Task identifier, e.g. ``"scrape_new_data"`` or
        ``"recompute_analytics"``.
    :type kind: str
    :param payload: Optional task-specific data.
    :type payload: dict or None
    :param headers: Optional AMQP message headers.
    :type headers: dict or None
    :raises Exception: Re-raises any broker error so the caller can
        return an appropriate HTTP error response.
    :returns: None.
    :rtype: None
    """
    body = json.dumps(
        {
            "kind": kind,
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "payload": payload or {},
        },
        separators=(",", ":"),
    ).encode("utf-8")
    conn, ch = _open_channel()
    try:
        ch.basic_publish(
            exchange=EXCHANGE,
            routing_key=ROUTING_KEY,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=2,
                headers=headers or {},
            ),
            mandatory=False,
        )
    finally:
        conn.close()
