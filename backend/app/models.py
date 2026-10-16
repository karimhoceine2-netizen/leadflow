from typing import Literal
from uuid import UUID
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class LeadCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid", strict=True)

    name: str = Field(min_length=2, max_length=120)
    email: EmailStr = Field(max_length=254)
    company_name: str = Field(min_length=2, max_length=160)
    description: str = Field(min_length=10, max_length=2000)

    @field_validator("name", "company_name", "description", mode="before")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("must be text")
        if any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("contains invalid characters")
        return value


class LeadResponse(BaseModel):
    id: UUID
    status: Literal["new", "contacted", "qualified", "closed"]
    duplicate: bool = False


LeadStatus = Literal["new", "contacted", "qualified", "closed"]


class AutomationInfo(BaseModel):
    # A receipt is evidence of processing; delivery state alone is not.
    status: Literal["not_scheduled", "pending", "processed", "failed", "unavailable"] = "unavailable"
    delivery_state: Literal["pending", "delivered", "dead"] | None = None
    attempts: int = Field(default=0, ge=0)
    processed_at: datetime | None = None
    priority: Literal["normal", "review_urgency"] | None = None

    @field_validator("processed_at", mode="after")
    @classmethod
    def utc_date(cls, value: datetime | None):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


class LeadRecord(BaseModel):
    id: UUID
    name: str
    email: str
    company_name: str
    description: str
    status: LeadStatus
    version: int
    created_at: datetime
    updated_at: datetime
    automation: AutomationInfo = Field(default_factory=AutomationInfo)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def utc_dates(cls, value: datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class StatusEvent(BaseModel):
    id: UUID
    previous_status: LeadStatus
    new_status: LeadStatus
    actor: str
    created_at: datetime

    @field_validator("created_at", mode="after")
    @classmethod
    def utc_date(cls, value: datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class LeadDetail(LeadRecord):
    history: list[StatusEvent] = Field(default_factory=list)


class LeadPage(BaseModel):
    items: list[LeadRecord]
    total: int
    page: int
    page_size: int
    counts: dict[str, int]


class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: LeadStatus
    expected_version: int = Field(ge=0)


class AdminCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)


class AdminSetup(AdminCredentials):
    password: str = Field(min_length=15, max_length=128)
