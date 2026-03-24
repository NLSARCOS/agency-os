import asyncio
from kernel.model_router import ModelRouter

async def test_required():
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
    prompt = "Create a file named 'FINAL.txt' with the text '123'"
    
    # We will monkeypatch or directly call with an overridden tool_choice
    class RouterWithForce(ModelRouter):
        def _call_openai_compatible(
            self, model: str, provider: str, prompt: str, system: str, start: float, tools: list[dict] | None = None, raw_messages: list[dict] | None = None
        ):
            # Same as original, but force tool_choice="required"
            import httpx, time
            endpoint = "https://openrouter.ai/api/v1/chat/completions"
            api_key = self._cfg.api_keys.get("openrouter", "")
            
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "HTTP-Referer": "https://agency-os.local"}
            messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
            payload = {"model": "anthropic/claude-3-haiku", "messages": messages}
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "required"
                
            with httpx.Client(timeout=20.0) as client:
                print("Sending request with tool_choice=required...")
                resp = client.post(endpoint, headers=headers, json=payload)
                
            if resp.status_code != 200:
                print(f"Error {resp.status_code}: {resp.text}")
                return
            data = resp.json()
            choice = data["choices"][0]
            print(f"Tool calls: {choice['message'].get('tool_calls')}")
            
    r = RouterWithForce()
    r._call_openai_compatible(
        model="anthropic/claude-3-haiku",
        provider="openrouter",
        prompt=prompt,
        system="You are an assistant.",
        start=0,
        tools=tools,
        raw_messages=None
    )

if __name__ == "__main__":
    asyncio.run(test_required())
