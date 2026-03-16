"""
Example Plugin: Pipeline Notifier

Demonstrates how to create an Agency OS plugin.
Sends notifications when pipelines complete.
"""


def setup(config: dict) -> None:
    """Called when plugin is loaded."""
    print(f"[plugin:example-notifier] Loaded with config: {config}")


def register_tools(tool_executor) -> None:
    """Register tools with the tool executor."""
    # Could register a 'send_notification' tool here
    pass


def on_pipeline_complete(studio: str, result: dict) -> None:
    """Hook called after pipeline completion."""
    success = result.get("success", False)
    print(f"[plugin:example-notifier] {studio} → {'✅' if success else '❌'}")
