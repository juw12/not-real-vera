"""Small Buffer GraphQL client. The API key is read from outside the repo and is never printed."""
import json
import os
import time
from pathlib import Path

import requests

BUFFER_API = "https://api.buffer.com"
KEY_FILE = Path.home() / ".notrealvera" / "buffer_key.txt"


class BufferError(RuntimeError):
    """Raised when Buffer cannot be reached or rejects a request."""


def load_api_key():
    """Return (key, where it came from). Order: BUFFER_API_KEY, then the channel's own key file.

    Only a key placed for this channel is used; keys belonging to other projects are never read.
    """
    env_key = os.environ.get("BUFFER_API_KEY", "").strip()
    if env_key:
        return env_key, "environment variable BUFFER_API_KEY"
    if KEY_FILE.exists():
        file_key = KEY_FILE.read_text(encoding="utf-8").strip()
        if file_key:
            return file_key, str(KEY_FILE)
    raise BufferError(f"No Buffer API key. Set BUFFER_API_KEY or put the key in {KEY_FILE}.")


def graphql(api_key, query, variables=None, attempts=4, post=requests.post):
    """POST one GraphQL request, retrying network errors (the office proxy drops TLS now and then)."""
    last_error = None
    for attempt in range(attempts):
        try:
            response = post(
                BUFFER_API,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"query": query, "variables": variables or {}},
                timeout=30,
            )
        except requests.exceptions.RequestException as error:
            last_error = error
            time.sleep(2 * (attempt + 1))
            continue
        if response.status_code == 429:
            last_error = BufferError("rate limited (429)")
            time.sleep(10 * (attempt + 1))
            continue
        try:
            payload = response.json()
        except ValueError as error:
            raise BufferError(f"Buffer returned HTTP {response.status_code} without JSON") from error
        if response.status_code != 200 and not payload.get("errors"):
            raise BufferError(f"Buffer returned HTTP {response.status_code}")
        return payload
    raise BufferError(f"Buffer unreachable after {attempts} attempts: {type(last_error).__name__}")


def list_channels(api_key):
    """Return every channel on the login as dicts with id, name, service."""
    payload = graphql(api_key, "query { account { organizations { id name } } }")
    if payload.get("errors"):
        raise BufferError(f"account query failed: {payload['errors'][0].get('message')}")
    channels = []
    for organization in payload["data"]["account"]["organizations"]:
        result = graphql(
            api_key,
            "query Channels($input: ChannelsInput!) { channels(input: $input) "
            "{ id name displayName service isDisconnected } }",
            {"input": {"organizationId": organization["id"]}},
        )
        if result.get("errors"):
            raise BufferError(f"channels query failed: {result['errors'][0].get('message')}")
        for channel in result["data"]["channels"]:
            channels.append(
                {
                    "id": channel["id"],
                    "name": channel.get("displayName") or channel.get("name") or "",
                    "service": (channel.get("service") or "").lower(),
                    "disconnected": bool(channel.get("isDisconnected")),
                }
            )
    return channels


TYPE_QUERY = """
query TypeFields($name: String!) {
  __type(name: $name) {
    name
    enumValues { name }
    inputFields {
      name
      type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
    }
  }
}
"""


def _unwrap(type_node):
    if type_node is None:
        return "?", None
    if type_node["kind"] == "NON_NULL":
        text, name = _unwrap(type_node["ofType"])
        return text + "!", name
    if type_node["kind"] == "LIST":
        text, name = _unwrap(type_node["ofType"])
        return "[" + text + "]", name
    return type_node["name"], type_node["name"]


def dump_input_schema(api_key, root="CreatePostInput", limit=80):
    """Walk the input types reachable from CreatePostInput and return them as readable lines."""
    scalars = {"String", "Boolean", "Int", "Float", "ID", "DateTime"}
    pending = [root]
    seen = set()
    lines = []
    while pending and len(seen) < limit:
        type_name = pending.pop(0)
        if type_name in seen or type_name in scalars:
            continue
        seen.add(type_name)
        payload = graphql(api_key, TYPE_QUERY, {"name": type_name})
        type_info = (payload.get("data") or {}).get("__type")
        if not type_info:
            lines.append(f"{type_name}: unavailable")
            continue
        if type_info.get("enumValues"):
            lines.append(f"enum {type_name}: " + ", ".join(value["name"] for value in type_info["enumValues"]))
            continue
        fields = []
        for field in type_info.get("inputFields") or []:
            signature, inner_name = _unwrap(field["type"])
            fields.append(f"{field['name']}: {signature}")
            if inner_name and inner_name not in seen:
                pending.append(inner_name)
        lines.append(f"input {type_name} {{ " + "; ".join(fields) + " }")
    return lines


if __name__ == "__main__":
    key, source = load_api_key()
    schema_lines = dump_input_schema(key)
    target = Path(__file__).resolve().parent.parent / "docs" / "buffer_schema.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(schema_lines) + "\n", encoding="utf-8", newline="\n")
    print(f"key from {source}; wrote {len(schema_lines)} types to {target}")
