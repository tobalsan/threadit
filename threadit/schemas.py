from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from threadit.db import AreaColor


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterIn(Strict):
    username: str = Field(pattern=r"^[A-Za-z0-9_-]{3,32}$")
    account_type: Literal["human", "agent"]
    description: str = Field("", max_length=1000)

    @model_validator(mode="after")
    def agent_needs_description(self):
        if self.account_type == "agent" and not self.description:
            raise ValueError("description is required for agent accounts")
        return self


class MePatch(Strict):
    description: str | None = Field(default=None, max_length=1000)
    email: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def description_not_null(self):
        if "description" in self.model_fields_set and self.description is None:
            raise ValueError("description must be a string")
        return self


class LoginIn(Strict):
    token: str = Field(min_length=1, max_length=200)


class AreaIn(Strict):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field("", max_length=10000)


class AreaPatch(Strict):
    name: str | None = Field(None, min_length=1, max_length=80)
    description: str | None = Field(None, max_length=10000)
    color: AreaColor | None = None

    @model_validator(mode="after")
    def color_not_null(self):
        if "color" in self.model_fields_set and self.color is None:
            raise ValueError("color must be a preset name")
        return self


class ThreadIn(Strict):
    area_id: int
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    attachment_ids: list[int] = Field(default_factory=list, max_length=10)


class ThreadPatch(Strict):
    title: str = Field(min_length=1, max_length=200)


class MessageIn(Strict):
    body: str = Field(min_length=1, max_length=20000)
    parent_id: int | None = None
    attachment_ids: list[int] = Field(default_factory=list, max_length=10)


class MessagePatch(Strict):
    body: str | None = Field(None, min_length=1, max_length=20000)
    attachment_ids: list[int] | None = Field(None, max_length=10)

    @model_validator(mode="after")
    def needs_a_change(self):
        if self.body is None and self.attachment_ids is None:
            raise ValueError("give body and/or attachment_ids")
        return self


class CloseIn(Strict):
    reason: Literal["completed", "archived"]


class ParkIn(Strict):
    until: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

    @model_validator(mode="after")
    def valid_date(self):
        date.fromisoformat(self.until)
        return self


class PinIn(Strict):
    pinned: bool


class VoteIn(Strict):
    delta: Literal[-100, -10, -5, -1, 1, 5, 10, 100]


class ReactionIn(Strict):
    emoji: str = Field(min_length=1, max_length=32, pattern=r"^\S+$")


class AgentActivityIn(Strict):
    kind: Literal["thought", "action", "elicitation", "error"]
    body: str = Field(min_length=1, max_length=2000)
    ephemeral: bool = False
