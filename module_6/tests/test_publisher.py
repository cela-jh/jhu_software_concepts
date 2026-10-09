"""
`test_publisher.py`
Verifies that publisher.py's stub functions raise NotImplementedError until
Section 4 provides real RabbitMQ implementations.
"""
import pytest

import publisher


@pytest.mark.integration
def test_constants_defined():
    """EXCHANGE, QUEUE, and ROUTING_KEY must be present and non-empty."""
    assert publisher.EXCHANGE
    assert publisher.QUEUE
    assert publisher.ROUTING_KEY


@pytest.mark.integration
def test_open_channel_raises_not_implemented():
    """_open_channel is a stub until Section 4."""
    with pytest.raises(NotImplementedError):
        publisher._open_channel()


@pytest.mark.integration
def test_publish_task_raises_not_implemented():
    """publish_task is a stub until Section 4."""
    with pytest.raises(NotImplementedError):
        publisher.publish_task("scrape_new_data")
