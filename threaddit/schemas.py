from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    description: str = Field(max_length=1000)


class LoginIn(Strict):
    token: str = Field(min_length=1, max_length=200)


class AreaIn(Strict):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field("", max_length=10000)


class AreaPatch(Strict):
    name: str | None = Field(None, min_length=1, max_length=80)
    description: str | None = Field(None, max_length=10000)


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
    body: str = Field(min_length=1, max_length=20000)


class CloseIn(Strict):
    reason: Literal["completed", "archived"]


class PinIn(Strict):
    pinned: bool


class VoteIn(Strict):
    delta: Literal[-100, -10, -5, -1, 1, 5, 10, 100]


class ReactionIn(Strict):
    emoji: str = Field(min_length=1, max_length=32, pattern=r"^\S+$")
