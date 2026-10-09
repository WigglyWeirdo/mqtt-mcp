from functools import partial

from fastmcp import FastMCP
from fastmcp.prompts import Message
from fastmcp.resources import ResourceTemplate
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from mqtt_mcp.mqtt_client import AsyncMQTTClient
from mqtt_mcp.settings import Settings, Topic


class MQTTMCP(FastMCP):
    def __init__(self, **kwargs):
        self.settings = Settings()

        auth = None
        if self.settings.auth.domain and self.settings.auth.url:
            from fastmcp.server.auth.providers.workos import AuthKitProvider

            auth = AuthKitProvider(
                authkit_domain=self.settings.auth.domain,
                base_url=self.settings.auth.url,
            )

        super().__init__(
            name="MQTT MCP Server",
            auth=auth,
            **kwargs,
        )

        self.add_template(
            ResourceTemplate.from_function(
                fn=self.receive_message, uri_template="mqtt://{host}:{port}/{topic*}"
            )
        )

        self.tool(
            self.receive_message,
            annotations={
                "title": "Receive Message",
                "readOnlyHint": True,
                "openWorldHint": True,
            },
        )

        self.tool(
            self.publish_message,
            annotations={
                "title": "Publish Message",
                "readOnlyHint": False,
                "openWorldHint": True,
            },
        )

        self.prompt(self.mqtt_error, name="mqtt_error", tags={"mqtt", "error"})
        self.prompt(self.mqtt_help, name="mqtt_help", tags={"mqtt", "help"})

        self.custom_route("/health", methods=["GET"])(self.health_check)

        self._topics: dict[str, Topic] = {}
        for topic in self.settings.topics:
            self.add_topic(topic)

        self._tool_names: set[str] = {"receive_message", "publish_message"}
        for topic in self.settings.tools:
            self.add_topic_tool(topic)

    def add_topic_tool(self, topic: Topic) -> None:
        """Exposes an MQTT topic as MCP tools that need no connection details.

        With `topic.type` set, a single tool named `topic.name` is registered. The
        publish tool takes only `message`, and the receive tool takes an optional
        `timeout`. Without `type`, a `{name}_receive` and a `{name}_publish` tool
        are registered. The topic, username and password are fixed by the
        configuration and are never exposed to the AI.
        """
        kinds = (topic.type,) if topic.type else ("receive", "publish")
        description = topic.description or f"MQTT topic {topic.topic!r}"
        for kind in kinds:
            name = topic.name if topic.type else f"{topic.name}_{kind}"
            if name in self._tool_names:
                raise ValueError(f"Tool {name!r} is already registered")
            self._tool_names.add(name)

            if kind == "receive":

                async def receive(timeout: int = 60) -> str:
                    return await self._receive_topic(topic, timeout)

                self.tool(
                    receive,
                    name=name,
                    description=f"Receive a message. {description}.",
                    annotations={
                        "title": f"Receive from {topic.topic}",
                        "readOnlyHint": True,
                        "openWorldHint": True,
                    },
                )
            else:

                async def publish(message: str) -> str:
                    return await self._publish_topic(topic, message)

                self.tool(
                    publish,
                    name=name,
                    description=f"Publish a message. {description}.",
                    annotations={
                        "title": f"Publish to {topic.topic}",
                        "readOnlyHint": False,
                        "openWorldHint": True,
                    },
                )

    def add_topic(self, topic: Topic) -> None:
        """Exposes an MQTT topic as resource templates.

        The templates are named after `topic.name`, for example
        `mqtt://topics/{name}/receive{?timeout}` and
        `mqtt://topics/{name}/publish/{message*}`. `topic.type` limits the topic to
        one of them; by default both are registered. The topic, username and
        password are passed to the MQTT client on every call; they are never part
        of the URI.
        """
        if topic.name in self._topics:
            raise ValueError(f"Topic {topic.name!r} is already registered")
        self._topics[topic.name] = topic

        description = topic.description or f"MQTT topic {topic.topic!r}"
        if topic.type in (None, "receive"):
            self.add_template(
                ResourceTemplate.from_function(
                    fn=partial(self._receive_topic, topic),
                    uri_template=f"mqtt://topics/{topic.name}/receive{{?timeout}}",
                    name=f"receive_{topic.name}",
                    description=f"Receive a message. {description}.",
                )
            )
        if topic.type in (None, "publish"):
            self.add_template(
                ResourceTemplate.from_function(
                    fn=partial(self._publish_topic, topic),
                    uri_template=f"mqtt://topics/{topic.name}/publish/{{message*}}",
                    name=f"publish_{topic.name}",
                    description=f"Publish a message. {description}.",
                )
            )

    def http_middleware(self) -> list[Middleware]:
        """Returns HTTP middleware to pass to `run(transport="http", middleware=...)`.

        CORS is enabled only for the origins in `cors_origins`, so browser clients
        such as web UIs on other origins can call the server. Without origins, no
        CORS headers are sent.
        """
        if not self.settings.cors_origins:
            return []
        return [
            Middleware(
                CORSMiddleware,
                allow_origins=self.settings.cors_origins,
                allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                allow_headers=["*"],
                expose_headers=["Mcp-Session-Id"],
            )
        ]

    async def _receive_topic(self, topic: Topic, timeout: int = 60) -> str:
        return await self.receive_message(
            topic.topic,
            username=topic.username,
            password=topic.password,
            timeout=timeout,
        )

    async def _publish_topic(self, topic: Topic, message: str) -> str:
        return await self.publish_message(
            topic.topic,
            message,
            username=topic.username,
            password=topic.password,
        )

    async def receive_message(
        self,
        topic: str,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: int = 60,
    ) -> str:
        """Receives a message published to the specified topic, if any."""
        async with AsyncMQTTClient(
            host if host is not None else self.settings.mqtt.host,
            port if port is not None else self.settings.mqtt.port,
            username if username is not None else self.settings.mqtt.username,
            password if password is not None else self.settings.mqtt.password,
        ) as client:
            return await client.receive(topic, timeout)

    async def publish_message(
        self,
        topic: str,
        message: str,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> str:
        """Publishes a message to the specified topic."""
        host = host if host is not None else self.settings.mqtt.host
        port = port if port is not None else self.settings.mqtt.port
        async with AsyncMQTTClient(
            host,
            port,
            username if username is not None else self.settings.mqtt.username,
            password if password is not None else self.settings.mqtt.password,
        ) as client:
            await client.publish(topic, message)
        return f"Publish to {topic} on {host}:{port} succeeded"

    def mqtt_help(self) -> list[Message]:
        """Provides examples of how to use the MQTT MCP server."""
        return [
            Message("Here are examples of how to publish and receives messages:"),
            Message('Publish {"foo":"bar"} to topic "devices/foo" on 127.0.0.1:1883.'),
            Message(
                'Receive a message from topic "devices/bar", waiting up to 30 seconds.'
            ),
        ]

    def mqtt_error(self, error: str | None = None) -> list[Message]:
        """Asks the user how to handle an error."""
        return (
            [
                Message(f"ERROR: {error!r}"),
                Message("Would you like to retry, change parameters, or abort?"),
            ]
            if error
            else []
        )

    async def health_check(self, request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})
