import pytest

from application.outcome_ports import NotificationDeliveryError


def test_permanent_error_keeps_flag():
    error = NotificationDeliveryError("chat not found", permanent=True)
    assert error.permanent is True
    assert str(error) == "chat not found"


def test_transient_error_keeps_flag():
    error = NotificationDeliveryError("timeout", permanent=False)
    assert error.permanent is False
    assert str(error) == "timeout"


def test_error_is_exception_subclass():
    assert issubclass(NotificationDeliveryError, Exception)


def test_raising_and_catching_preserves_flag():
    with pytest.raises(NotificationDeliveryError) as excinfo:
        raise NotificationDeliveryError("blocked by user", permanent=True)
    assert excinfo.value.permanent is True
