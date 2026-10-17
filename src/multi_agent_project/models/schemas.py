from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        """Reject empty input after removing surrounding whitespace."""
        value = value.strip()
        if not value:
            raise ValueError("Message must not be empty")
        return value


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    agents_used: list[str] = Field(default_factory=list)
    tools_called: list[str] = Field(default_factory=list)
