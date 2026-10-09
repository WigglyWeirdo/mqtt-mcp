import asyncio

import pytest
from fastmcp import Client
from starlette.requests import Request

from mqtt_mcp.mqtt_client import _resolve_host
from mqtt_mcp.server import MQTTMCP
from mqtt_mcp.settings import Topic


@pytest.mark.asyncio
async def test_receive_message(server, mcp, client):
    """Test receive_message."""
    topic = "foo"
    message = '{"bar":123}'

    async def pub():
        await asyncio.sleep(1.0)
        return await client.call_tool(
            "publish_message",
            {
                "topic": topic,
                "message": message,
                "host": server.host,
                "port": server.port,
            },
        )

    sub = None
    async with asyncio.TaskGroup() as tg:
        sub = tg.create_task(
            client.call_tool(
                "receive_message",
                {
                    "topic": topic,
                    "host": server.host,
                    "port": server.port,
                    "timeout": 3,
                },
            )
        )
        tg.create_task(pub())

    result = sub.result()
    assert len(result.content) == 1
    assert result.content[0].text == message


@pytest.mark.asyncio
async def test_receive_message_wildcard(server, client):
    subscription = "devices/+/data"
    topic = "devices/12345/data"
    message = '{"temperature":21.5}'

    async def pub():
        await asyncio.sleep(1.0)
        await client.call_tool(
            "publish_message",
            {
                "topic": topic,
                "message": message,
                "host": server.host,
                "port": server.port,
            },
        )

    async with asyncio.TaskGroup() as tg:
        sub = tg.create_task(
            client.call_tool(
                "receive_message",
                {
                    "topic": subscription,
                    "host": server.host,
                    "port": server.port,
                    "timeout": 3,
                },
            )
        )
        tg.create_task(pub())

    result = sub.result()
    assert result.content[0].text == message


@pytest.mark.asyncio
async def test_publish_message(server, mcp, client):
    """Test publish_message."""
    result = await client.call_tool(
        "publish_message",
        {
            "topic": "foo",
            "message": '{"bar":456}',
            "host": server.host,
            "port": server.port,
        },
    )
    assert len(result.content) == 1
    assert "succeeded" in result.content[0].text


@pytest.mark.asyncio
async def test_help_prompt(mcp, client):
    """Test help prompt."""
    result = await client.get_prompt("mqtt_help", {})
    assert len(result.messages) == 3


@pytest.mark.asyncio
async def test_error_prompt(mcp, client):
    """Test error prompt."""
    result = await client.get_prompt("mqtt_error", {"error": "Could not read data"})
    assert len(result.messages) == 2


@pytest.mark.asyncio
async def test_health_check(mcp):
    response = await mcp.health_check(
        Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/health",
                "headers": [],
            }
        )
    )
    assert response.status_code == 200


def test_resolve_host_localhost():
    """_resolve_host should resolve 'localhost' to an IP address."""
    result = _resolve_host("localhost")
    # Should be an IP, not the original string
    assert result in ("127.0.0.1", "::1")


def test_resolve_host_ip_passthrough():
    """_resolve_host should return an IP address unchanged."""
    result = _resolve_host("127.0.0.1")
    assert result == "127.0.0.1"


def test_resolve_host_unresolvable():
    """_resolve_host should return the original string when resolution fails."""
    result = _resolve_host("this.host.does.not.exist.invalid")
    assert result == "this.host.does.not.exist.invalid"


@pytest.fixture()
def isolated_cwd(tmp_path, monkeypatch):
    """Run in an empty directory so a developer's .env cannot leak into Settings."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MQTT_MCP_TOPICS", raising=False)
    return tmp_path


@pytest.mark.asyncio
async def test_add_topic_registers_templates(isolated_cwd):
    mcp = MQTTMCP()
    mcp.add_topic(Topic(name="temp", topic="devices/temp", description="Room temp"))

    async with Client(mcp) as client:
        uris = {t.uri_template for t in await client.list_resource_templates()}

    assert "mqtt://topics/temp/receive{?timeout}" in uris
    assert "mqtt://topics/temp/publish/{message*}" in uris


def test_add_topic_duplicate_raises(isolated_cwd):
    mcp = MQTTMCP()
    mcp.add_topic(Topic(name="temp", topic="devices/temp"))
    with pytest.raises(ValueError):
        mcp.add_topic(Topic(name="temp", topic="devices/other"))


@pytest.mark.asyncio
async def test_topics_from_env(isolated_cwd, monkeypatch):
    monkeypatch.setenv(
        "MQTT_MCP_TOPICS",
        '[{"name":"env_temp","topic":"devices/+/temp","username":"u","password":"p"}]',
    )
    mcp = MQTTMCP()

    async with Client(mcp) as client:
        uris = {t.uri_template for t in await client.list_resource_templates()}

    assert "mqtt://topics/env_temp/receive{?timeout}" in uris
    assert "mqtt://topics/env_temp/publish/{message*}" in uris


@pytest.mark.asyncio
async def test_topic_templates_pass_topic_and_credentials(isolated_cwd, monkeypatch):
    """Topic, username and password from the topic definition reach the MQTT client."""
    calls = []

    class FakeMQTTClient:
        def __init__(self, host, port, username=None, password=None):
            self.args = (host, port, username, password)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def receive(self, topic, timeout=60, qos=1):
            calls.append(("receive", self.args, topic, timeout))
            return "payload"

        async def publish(self, topic, message, qos=1):
            calls.append(("publish", self.args, topic, message))

    monkeypatch.setattr("mqtt_mcp.server.AsyncMQTTClient", FakeMQTTClient)

    mcp = MQTTMCP()
    mcp.add_topic(
        Topic(
            name="secure", topic="devices/secure", username="sensor", password="s3cret"
        )
    )

    async with Client(mcp) as client:
        received = await client.read_resource("mqtt://topics/secure/receive?timeout=7")
        await client.read_resource("mqtt://topics/secure/publish/hello")

    assert received[0].text == "payload"
    assert calls == [
        ("receive", ("127.0.0.1", 1883, "sensor", "s3cret"), "devices/secure", 7),
        ("publish", ("127.0.0.1", 1883, "sensor", "s3cret"), "devices/secure", "hello"),
    ]


@pytest.mark.asyncio
async def test_topic_templates_fall_back_to_global_credentials(
    isolated_cwd, monkeypatch
):
    monkeypatch.setenv("MQTT_MCP_MQTT__USERNAME", "gateway")
    monkeypatch.setenv("MQTT_MCP_MQTT__PASSWORD", "g4teway")
    calls = []

    class FakeMQTTClient:
        def __init__(self, host, port, username=None, password=None):
            calls.append((host, port, username, password))

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def publish(self, topic, message, qos=1):
            calls.append(topic)

    monkeypatch.setattr("mqtt_mcp.server.AsyncMQTTClient", FakeMQTTClient)

    mcp = MQTTMCP()
    mcp.add_topic(Topic(name="plain", topic="devices/plain"))

    async with Client(mcp) as client:
        await client.read_resource("mqtt://topics/plain/publish/hi")

    assert calls == [("127.0.0.1", 1883, "gateway", "g4teway"), "devices/plain"]


@pytest.mark.asyncio
async def test_topic_receive_and_publish_round_trip(isolated_cwd):
    mcp = MQTTMCP()
    mcp.add_topic(Topic(name="roundtrip", topic="devices/roundtrip"))
    message = '{"status":"on"}'

    async def pub(client):
        await asyncio.sleep(1.0)
        await client.read_resource(f"mqtt://topics/roundtrip/publish/{message}")

    async with Client(mcp) as client, asyncio.TaskGroup() as tg:
        sub = tg.create_task(
            client.read_resource("mqtt://topics/roundtrip/receive?timeout=3")
        )
        tg.create_task(pub(client))

    assert sub.result()[0].text == message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (None, {"receive", "publish"}),
        ("receive", {"receive"}),
        ("publish", {"publish"}),
    ],
)
async def test_topic_type_limits_templates(isolated_cwd, kind, expected):
    mcp = MQTTMCP()
    mcp.add_topic(Topic(name="typed", topic="devices/typed", type=kind))

    async with Client(mcp) as client:
        uris = {t.uri_template for t in await client.list_resource_templates()}

    registered = {
        verb
        for verb in ("receive", "publish")
        if any(f"mqtt://topics/typed/{verb}" in uri for uri in uris)
    }
    assert registered == expected


def test_topic_type_from_env(isolated_cwd, monkeypatch):
    monkeypatch.setenv(
        "MQTT_MCP_TOPICS",
        '[{"name":"only_pub","topic":"devices/p","type":"publish"}]',
    )
    assert MQTTMCP().settings.topics[0].type == "publish"


def test_topic_invalid_type_rejected():
    with pytest.raises(ValueError):
        Topic.model_validate(
            {"name": "bad", "topic": "devices/bad", "type": "subscribe"}
        )


async def _asgi_request(app, method, path, headers):
    """Sends one request to an ASGI app and returns (status, lowercased headers)."""
    messages = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 1234),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    return start["status"], {
        k.decode().lower(): v.decode() for k, v in start["headers"]
    }


@pytest.mark.asyncio
async def test_cors_preflight_allowed_origin(isolated_cwd, monkeypatch):
    monkeypatch.setenv("MQTT_MCP_CORS_ORIGINS", '["https://ui.example.com"]')
    mcp = MQTTMCP()
    app = mcp.http_app(middleware=mcp.http_middleware())

    status, headers = await _asgi_request(
        app,
        "OPTIONS",
        "/mcp",
        [
            ("Origin", "https://ui.example.com"),
            ("Access-Control-Request-Method", "POST"),
            ("Access-Control-Request-Headers", "content-type,mcp-protocol-version"),
        ],
    )

    assert status == 200
    assert headers["access-control-allow-origin"] == "https://ui.example.com"
    assert "POST" in headers["access-control-allow-methods"]


@pytest.mark.asyncio
async def test_cors_rejects_other_origin(isolated_cwd, monkeypatch):
    monkeypatch.setenv("MQTT_MCP_CORS_ORIGINS", '["https://ui.example.com"]')
    mcp = MQTTMCP()
    app = mcp.http_app(middleware=mcp.http_middleware())

    _, headers = await _asgi_request(
        app,
        "OPTIONS",
        "/mcp",
        [
            ("Origin", "https://evil.example"),
            ("Access-Control-Request-Method", "POST"),
        ],
    )

    assert "access-control-allow-origin" not in headers


def test_http_middleware_empty_without_origins(isolated_cwd):
    assert MQTTMCP().http_middleware() == []


def test_cors_origins_from_env(isolated_cwd, monkeypatch):
    monkeypatch.setenv(
        "MQTT_MCP_CORS_ORIGINS", '["https://a.example","https://b.example"]'
    )
    assert MQTTMCP().settings.cors_origins == ["https://a.example", "https://b.example"]
