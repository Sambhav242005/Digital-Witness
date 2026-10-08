import pytest

from app.config import Settings
from app.service import Service


def test_service_lock_is_exclusive_and_released(tmp_path):
    settings = Settings(data_dir=tmp_path, worker_enabled=False)
    first = Service(settings, object(), object())
    second = Service(settings, object(), object())

    first.start()
    try:
        with pytest.raises(RuntimeError, match="exactly one backend server"):
            second.start()
    finally:
        first.close()

    second.start()
    second.close()
