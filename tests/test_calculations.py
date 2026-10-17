import pytest
from pydantic import ValidationError

from multi_agent_project.tools.calculations import calculate_data_volume


def test_normal_volume() -> None:
    """Convert daily ingestion into the expected total terabytes."""
    result = calculate_data_volume(500, 30)
    assert result["total_tb"] == 15


def test_zero_volume() -> None:
    """Allow zero ingestion and return zero total gigabytes."""
    result = calculate_data_volume(0, 30)
    assert result["total_gb"] == 0


def test_negative_volume() -> None:
    """Reject negative daily ingestion through Pydantic validation."""
    with pytest.raises(ValidationError):
        calculate_data_volume(-100, 30)
