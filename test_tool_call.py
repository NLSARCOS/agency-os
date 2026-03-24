import asyncio
from kernel.model_router import ModelRouter

async def test_tools():
    print("Testing OpenRouter tool call generation...")
    router = ModelRouter()
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write exact content to a specified file path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute or relative file path"},
                        "content": {"type": "string", "description": "Text content to write"}
                    },
                    "required": ["path", "content"]
                }
            }
        }
    ]
    
    prompt = "Create a file named 'POC_TOOL_CALL.txt' in the current directory containing exactly 'OK - tool test'."
    system = "You are a helpful assistant. You MUST use the provided write_file tool to complete the user's request."
    
    # Use standard args
    resp = await router.call_model(
        prompt=prompt,
        studio="dev",
        system=system,
        tools=tools
    )
    
    print("\n[RESPONSE DATA]")
    print(f"Content: {resp.content}")
    print(f"Tool Calls: {resp.tool_calls}")
    print(f"Model Used: {resp.model} ({resp.provider})")

if __name__ == "__main__":
    asyncio.run(test_tools())
