"""
`publisher.py`
RabbitMQ publisher for the web service. Enqueues tasks to be processed
asynchronously by the worker. Implemented in Section 4.
"""

# Exchange, queue, and routing key constants shared by publisher and consumer.
EXCHANGE = "tasks"
QUEUE = "tasks_q"
ROUTING_KEY = "tasks"


def _open_channel():
    """
    Open a RabbitMQ connection and channel, declaring the durable
    exchange, queue, and binding. Implemented in Section 4.

    :returns: (connection, channel) pair.
    :rtype: tuple
    """
    raise NotImplementedError("publisher._open_channel will be implemented in Section 4")


def publish_task(kind: str, payload: dict | None = None,
                 headers: dict | None = None) -> None:
    """
    Publish a task message to the tasks exchange. Implemented in
    Section 4.

    :param kind: Task identifier, e.g. ``"scrape_new_data"`` or
        ``"recompute_analytics"``.
    :type kind: str
    :param payload: Optional task-specific data.
    :type payload: dict or None
    :param headers: Optional AMQP message headers.
    :type headers: dict or None
    :raises NotImplementedError: Until Section 4 is complete.
    :returns: None.
    :rtype: None
    """
    raise NotImplementedError("publisher.publish_task will be implemented in Section 4")
