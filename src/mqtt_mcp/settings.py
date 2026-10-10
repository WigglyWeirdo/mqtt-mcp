from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Auth(BaseModel):
    domain: str | None = None
    url: str | None = None


class MQTT(BaseModel):
    host: str = "127.0.0.1"
    port: int = 1883
    username: str | None = None
    password: str | None = None


class Topic(BaseModel):
    """An MQTT topic exposed to agents as resource templates.

    `type` limits the topic to a single `receive` or `publish` template. When
    omitted, both templates are registered. Username and password fall back to
    the global `mqtt` settings when omitted.
    """

    name: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    topic: str = Field(min_length=1)
    type: Literal["receive", "publish"] | None = None
    description: str | None = None
    username: str | None = None
    password: str | None = None


class Settings(BaseSettings):
    auth: Auth = Auth()
    mqtt: MQTT = MQTT()
    topics: list[Topic] = []
    tools: list[Topic] = []
    tools_file: Path = Path("mqtt_mcp_tools.json")
    cors_origins: list[str] = []
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        env_prefix="MQTT_MCP_",
    )

    @model_validator(mode="after")
    def load_tools_file(self) -> "Settings":
        """Adds the tools in `tools_file`, when it exists, to those from the environment.

        A JSON list is used because repeating `MQTT_MCP_TOOLS` in `.env` silently keeps
        only the last value.
        """
        if self.tools_file.is_file():
            try:
                file_tools = TypeAdapter(list[Topic]).validate_json(
                    self.tools_file.read_bytes()
                )
            except ValidationError as e:
                raise ValueError(f"Invalid tools file {self.tools_file}: {e}") from e
            self.tools = [*self.tools, *file_tools]
        return self
