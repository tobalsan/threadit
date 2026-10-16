from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterIn(Strict):
    username: str = Field(pattern=r"^[A-Za-z0-9_-]{3,32}$")
    account_type: Literal["human", "agent"]


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


class MessageIn(Strict):
    body: str = Field(min_length=1, max_length=20000)
    parent_id: int | None = None


class CloseIn(Strict):
    reason: Literal["completed", "archived"]


class PinIn(Strict):
    pinned: bool


class VoteIn(Strict):
    delta: Literal[-100, -10, -5, -1, 1, 5, 10, 100]


class ReactionIn(Strict):
    emoji: str = Field(min_length=1, max_length=32, pattern=r"^\S+$")
