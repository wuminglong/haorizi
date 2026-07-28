from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from app.schemas import ReminderUpsertRequest


class AdminSessionRequest(BaseModel):
    password: str = Field(min_length=1, max_length=512)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_token_field(cls, value: object) -> object:
        # Accept token during the small transition from header-based admin auth.
        if isinstance(value, dict) and "password" not in value:
            for legacy_key in ("token", "admin_token"):
                if legacy_key in value:
                    return {**value, "password": value[legacy_key]}
        return value


class AdminReminderPayload(ReminderUpsertRequest):
    pass


class AdminReminderCreate(AdminReminderPayload):
    group_id: int = Field(gt=0)
