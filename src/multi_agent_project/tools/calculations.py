from pydantic import BaseModel, Field


class VolumeInput(BaseModel):
    daily_gb: float = Field(ge=0)
    days: int = Field(default=30, ge=1, le=366)


def calculate_data_volume(
    daily_gb: float,
    days: int = 30,
) -> dict:
    """Calculate total data volume from daily ingestion.

    Args:
        daily_gb: Gigabytes ingested per day.
        days: Number of days to calculate, from 1 to 366.

    Returns:
        Status, period, and rounded totals in decimal gigabytes and terabytes.

    Raises:
        pydantic.ValidationError: If ingestion is negative or days is out of range.
    """
    inputs = VolumeInput(
        daily_gb=daily_gb,
        days=days,
    )

    total_gb = inputs.daily_gb * inputs.days

    return {
        "total_gb": round(total_gb, 2),
        "total_tb": round(total_gb / 1000, 3),
        "days": inputs.days,
        "status": "success",
    }
