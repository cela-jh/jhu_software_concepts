"""
`consumer.py`
RabbitMQ consumer for the worker service. Connects to the broker,
declares durable AMQP entities, and routes incoming task messages to
the appropriate handler, acknowledging only after a successful DB commit.
"""
import json
import os

import pika
import psycopg

from etl.incremental_scraper import load_incremental
from etl.query_data import run_analytics

EXCHANGE = "tasks"
QUEUE = "tasks_q"
ROUTING_KEY = "tasks"

# Path to the seed JSON file, injected by Docker Compose via SEED_JSON.
SEED_JSON = os.environ.get("SEED_JSON", "/app/data/applicant_data.json")


def handle_scrape_new_data(conn, payload):
    """
    Load applicant records whose p_id exceeds the stored watermark from
    the seed JSON file into PostgreSQL. Advances the watermark after a
    successful batch insert. The caller owns commit/rollback.

    :param conn: An open psycopg connection.
    :type conn: psycopg.Connection
    :param payload: Task payload; may include a ``"since"`` key to
        override the watermark.
    :type payload: dict
    :returns: None.
    :rtype: None
    """
    since = payload.get("since")
    inserted = load_incremental(conn, SEED_JSON, since=since)
    print(f"Scraped {inserted} new record(s) from {SEED_JSON}.", flush=True)


def handle_recompute_analytics(conn, _payload):
    """
    Re-execute all analytics queries to verify and exercise the data,
    within the same per-message transaction. The caller owns
    commit/rollback.

    :param conn: An open psycopg connection.
    :type conn: psycopg.Connection
    :param _payload: Task payload (not used by this handler).
    :type _payload: dict
    :returns: None.
    :rtype: None
    """
    run_analytics(conn)
    print("Analytics recomputed.", flush=True)


# Task kind → handler function.
TASK_MAP = {
    "scrape_new_data": handle_scrape_new_data,
    "recompute_analytics": handle_recompute_analytics,
}


def _on_message(ch, method, _properties, body, conn):
    """
    Callback for each AMQP delivery. Routes by ``kind``, commits on
    success and acks, or rolls back and nacks on any error.

    :param ch: The AMQP channel.
    :param method: Delivery metadata (includes delivery_tag).
    :param _properties: AMQP message properties (unused).
    :param body: Raw message bytes.
    :param conn: An open psycopg connection (autocommit must be False).
    :type conn: psycopg.Connection
    :returns: None.
    :rtype: None
    """
    try:
        message = json.loads(body)
        kind = message.get("kind")
        payload = message.get("payload", {})
    except (json.JSONDecodeError, AttributeError):
        print(f"Malformed message body, discarding: {body!r}", flush=True)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    handler = TASK_MAP.get(kind)
    if handler is None:
        print(f"Unknown task kind {kind!r}, discarding.", flush=True)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    try:
        handler(conn, payload)
        conn.commit()
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as error:  # pylint: disable=broad-exception-caught
        print(f"Handler {kind!r} failed: {error}", flush=True)
        conn.rollback()
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def main():
    """
    Entry point: connect to PostgreSQL and RabbitMQ, declare durable
    AMQP entities, and start consuming from tasks_q with prefetch=1.

    :returns: None.
    :rtype: None
    """
    database_url = os.environ["DATABASE_URL"]
    rabbitmq_url = os.environ["RABBITMQ_URL"]

    db_conn = psycopg.connect(database_url)
    db_conn.autocommit = False

    mq_conn = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    ch = mq_conn.channel()

    ch.exchange_declare(exchange=EXCHANGE, exchange_type="direct", durable=True)
    ch.queue_declare(queue=QUEUE, durable=True)
    ch.queue_bind(exchange=EXCHANGE, queue=QUEUE, routing_key=ROUTING_KEY)
    ch.basic_qos(prefetch_count=1)

    ch.basic_consume(
        queue=QUEUE,
        on_message_callback=lambda ch, method, props, body: (
            _on_message(ch, method, props, body, db_conn)
        ),
    )

    print("Worker ready. Waiting for tasks.", flush=True)
    try:
        ch.start_consuming()
    except KeyboardInterrupt:
        ch.stop_consuming()
    finally:
        db_conn.close()
        mq_conn.close()


if __name__ == "__main__":
    main()
