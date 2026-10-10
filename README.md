## MQTT MCP Server

A lightweight [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that connects LLM agents to [MQTT](https://en.wikipedia.org/wiki/MQTT) devices in a secure, standardized way, enabling seamless integration of AI-driven workflows with Building Automation (BAS), Industrial Control (ICS) and Smart Home systems, allowing agents to monitor real-time sensor data, actuate devices, and orchestrate complex automation tasks.

[![test](https://github.com/ezhuk/mqtt-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/ezhuk/mqtt-mcp/actions/workflows/test.yml)
[![codecov](https://codecov.io/github/ezhuk/mqtt-mcp/graph/badge.svg?token=EPF2SIV44I)](https://codecov.io/github/ezhuk/mqtt-mcp)
[![PyPI - Version](https://img.shields.io/pypi/v/mqtt-mcp.svg)](https://pypi.org/p/mqtt-mcp)

## Getting Started

Use [uv](https://github.com/astral-sh/uv) to add and manage the MQTT MCP server as a dependency in your project, or install it directly via `uv pip install` or `pip install`. See the [Installation](https://github.com/ezhuk/mqtt-mcp/blob/main/docs/mqtt-mcp/installation.mdx) section of the documentation for full installation instructions and more details.

```bash
uv add mqtt-mcp
```

The server can be embedded in and run directly from your application. By default, it exposes a `Streamable HTTP` endpoint at `http://127.0.0.1:8000/mcp/`.

```python
# app.py
from mqtt_mcp import MQTTMCP

mcp = MQTTMCP()

if __name__ == "__main__":
    mcp.run(transport="http")
```

It can also be launched from the command line using the provided `CLI` without modifying the source code.

```bash
mqtt-mcp
```

Or in an ephemeral, isolated environment using `uvx`. Check out the [Using tools](https://docs.astral.sh/uv/guides/tools/) guide for more details.

```bash
uvx mqtt-mcp
```

### Configuration

For the use cases where most operations target a specific MQTT broker its connection settings (`host` and `port`) can be specified at runtime using environment variables so that all prompts that omit explicit connection parameters will be routed to this broker.

```bash
export MQTT_MCP_MQTT__HOST=10.0.0.1
export MQTT_MCP_MQTT__PORT=1883
```

These settings can also be specified in a `.env` file in the working directory.

```text
# .env
mqtt_mcp_mqtt__host=10.0.0.1
mqtt_mcp_mqtt__port=1883
```

### Topic Tools

Topics can also be exposed as MCP tools. A tool takes only what the AI needs to supply, such as a message. The topic, username and password come from the configuration.

Define tools in `.env` as a JSON list in `MQTT_MCP_TOOLS`. The entries use the same format as topics.

```text
# .env
mqtt_mcp_tools='[{"name":"PTZ_control_backyard","topic":"frigate/camera/ptz","description":"Move a camera","username":"user","password":"...","type":"publish"}]'
```

- With `"type"` set to `"publish"` or `"receive"`, one tool is registered under `name`. The publish tool takes a `message` argument. The receive tool takes an optional `timeout`.
- Without `"type"`, two tools are registered: `{name}_receive` and `{name}_publish`.

Tools can also be added in code with `mcp.add_topic_tool(Topic(...))`.

### Binary Messages

Messages that are not UTF-8 text are handled as follows. JPEG payloads are returned as an image: an image content block for tools, and an `image/jpeg` blob for resources. Other binary payloads return an error.

### Browser Clients (CORS)

Browser-based MCP clients on another origin (for example, a web UI served from a different host or port) need CORS. CORS is disabled by default. To allow specific origins, list them in `MQTT_MCP_CORS_ORIGINS` as a JSON list.

```text
# .env
mqtt_mcp_cors_origins='["https://ui.example.com:8080"]'
```

Use the MCP endpoint without a trailing slash (`/mcp`). The `/mcp/` form redirects, and the redirect can point at the internal address. When running behind a reverse proxy, the proxy must forward `/mcp` and keep the `Host` header.

If the server is embedded in your application, pass the same middleware to `run`.

```python
mcp = MQTTMCP()
mcp.run(transport="http", middleware=mcp.http_middleware())
```

### Topic Resource Templates

Individual topics can be exposed to agents as their own resource templates, so the agent can pick a topic from the list. Each topic gets a receive and a publish template. The topic, username and password are passed to the MQTT client; they are not part of the URI. Username and password fall back to `mqtt_mcp_mqtt__username` and `mqtt_mcp_mqtt__password` when omitted.

Topics are defined in the `.env` file as a JSON list. Use single quotes so the JSON is read as one value.

```text
# .env
mqtt_mcp_topics='[{"name":"living_room_temp","topic":"devices/living-room/temperature","description":"Living room temperature","username":"sensor","password":"s3cret"}]'
```

This registers two templates:

- `mqtt://topics/living_room_temp/receive{?timeout}` receives a message from the topic.
- `mqtt://topics/living_room_temp/publish/{message*}` publishes a message to the topic.

Set `"type"` to `"receive"` or `"publish"` to register only one of them. Omit it to register both.

```text
mqtt_mcp_topics='[{"name":"alarm","topic":"devices/alarm","type":"receive"},{"name":"lamp","topic":"devices/lamp/set","type":"publish"}]'
```

Topics can also be added in code, for example in `server.py` or in your application, before the server starts.

```python
from mqtt_mcp.server import MQTTMCP
from mqtt_mcp.settings import Topic

mcp = MQTTMCP()
mcp.add_topic(
    Topic(name="thermostat", topic="devices/thermostat/set", username="hvac", password="...")
)
```

### MCP Inspector

To confirm the server is up and running and explore available resources and tools, run the [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector) and connect it to the MQTT MCP server at `http://127.0.0.1:8000/mcp/`. Make sure to set the transport to `Streamable HTTP`.

```bash
npx @modelcontextprotocol/inspector
```

![s01](https://github.com/user-attachments/assets/6ee711b2-994d-4a89-a088-13ad77b09b0e)

## Core Concepts

The MQTT MCP server leverages FastMCP 2.0's core building blocks - resource templates, tools, and prompts - to streamline MQTT receive and publish operations with minimal boilerplate and a clean, Pythonic interface.

### Receive Message

Each topic on a device is mapped to a resource (and exposed as a tool) and [resource templates](https://gofastmcp.com/servers/resources#resource-templates) are used to specify connection details (host, port) and receive parameters (topic, timeout).

```python
@mcp.resource("mqtt://{host}:{port}/{topic*}")
@mcp.tool(
    annotations={
        "title": "Receive Message",
        "readOnlyHint": True,
        "openWorldHint": True,
    }
)
async def receive_message(
    topic: str,
    host: str = settings.mqtt.host,
    port: int = settings.mqtt.port,
    timeout: int = 60,
) -> str:
    """Receives a message published to the specified topic, if any."""
    ...
```

### Publish Message

Publish operations are exposed as a [tool](https://gofastmcp.com/servers/tools), accepting the same connection details (host, port) and allowing to publish a message to a specific topic in a single, atomic call.

```python
@mcp.tool(
    annotations={
        "title": "Publish Message",
        "readOnlyHint": False,
        "openWorldHint": True,
    }
)
async def publish_message(
    topic: str,
    message: str,
    host: str = settings.mqtt.host,
    port: int = settings.mqtt.port,
) -> str:
    """Publishes a message to the specified topic."""
    ...
```

### Authentication

To enable authentication using the built-in [AuthKit](https://www.authkit.com) provider for the `Streamable HTTP` transport, provide the AuthKit domain and redirect URL in the `.env` file. Check out the [AuthKit Provider](https://gofastmcp.com/servers/auth/remote-oauth#example%3A-workos-authkit-provider) section for more details.

### Interactive Prompts

Structured response messages are implemented using [prompts](https://gofastmcp.com/servers/prompts) that help guide the interaction, clarify missing parameters, and handle errors gracefully.

```python
@mcp.prompt(name="mqtt_help", tags={"mqtt", "help"})
def mqtt_help() -> list[Message]:
    """Provides examples of how to use the MQTT MCP server."""
    ...
```

Here are some example text inputs that can be used to interact with the server.

```text
Publish {"foo":"bar"} to topic "devices/foo" on 127.0.0.1:1883.
Receive a message from topic "devices/bar", waiting up to 30 seconds.
```

## Examples

The `examples` folder contains sample projects showing how to integrate with the MQTT MCP server using various client APIs to provide tools and context to LLMs.

- [openai-agents](https://github.com/ezhuk/mqtt-mcp/tree/main/examples/openai-agents) - shows how to connect to the MQTT MCP server using the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/mcp/).
- [openai](https://github.com/ezhuk/mqtt-mcp/tree/main/examples/openai) - a minimal app leveraging remote MCP server support in the [OpenAI Python library](https://platform.openai.com/docs/guides/tools-remote-mcp).
- [pydantic-ai](https://github.com/ezhuk/mqtt-mcp/tree/main/examples/pydantic-ai) - shows how to connect to the MQTT MCP server using the [PydanticAI Agent Framework](https://ai.pydantic.dev).

## Docker

The MQTT MCP server can be deployed as a Docker container as follows:

```bash
docker run -dit \
  --name mqtt-mcp \
  --restart=always \
  -p 8080:8000 \
  --env-file .env \
  ghcr.io/ezhuk/mqtt-mcp:latest
```

This maps port `8080` on the host to the MCP server's port `8000` inside the container and loads settings from the `.env` file, if present.

## License

The server is licensed under the [MIT License](https://github.com/ezhuk/mqtt-mcp?tab=MIT-1-ov-file).
