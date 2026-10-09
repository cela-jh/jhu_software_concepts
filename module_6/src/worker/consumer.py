"""
`consumer.py`
RabbitMQ consumer for the worker service. Connects to the broker,
declares durable AMQP entities, and routes incoming task messages to
the appropriate handler. Implemented in Section 4.
"""

# Exchange, queue, and routing key must match the publisher's constants.
EXCHANGE = "tasks"
QUEUE = "tasks_q"
ROUTING_KEY = "tasks"


def handle_scrape_new_data(conn, payload):
    """
    Load applicant records newer than the stored watermark from the seed
    JSON file into PostgreSQL. Advances the watermark after a successful
    batch insert. Implemented in Section 4.

    :param conn: An open psycopg connection. Caller owns the transaction.
    :type conn: psycopg.Connection
    :param payload: Task payload; may include a ``"since"`` key to
        override the watermark.
    :type payload: dict
    :returns: None.
    :rtype: None
    """
    raise NotImplementedError("handle_scrape_new_data will be implemented in Section 4")


def handle_recompute_analytics(conn, payload):
    """
    Recompute summaries and analytics used by the UI. Implemented in
    Section 4.

    :param conn: An open psycopg connection. Caller owns the transaction.
    :type conn: psycopg.Connection
    :param payload: Task payload (currently unused).
    :type payload: dict
    :returns: None.
    :rtype: None
    """
    raise NotImplementedError("handle_recompute_analytics will be implemented in Section 4")


def main():
    """
    Entry point: connect to RabbitMQ and start consuming from tasks_q.
    Implemented in Section 4.

    :returns: None.
    :rtype: None
    """
    raise NotImplementedError("consumer.main will be implemented in Section 4")


if __name__ == "__main__":
    main()
