#!/usr/bin/env python3
"""
Agency OS v3.5 — MCP Server
Provides tools for OpenClaw to read Agency OS status.
"""
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Agency OS", description="Agency OS Internal Task Board Tools")

@mcp.tool()
async def get_active_missions() -> str:
    """Get the status of all currently active (running or queued) missions in Agency OS. Use this when the user asks 'what is the status of my tasks?' or 'how is the agency doing?'"""
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get("http://localhost:8080/api/missions/active", timeout=5)
            if r.status_code == 200:
                data = r.json()
                count = data.get("count", 0)
                missions = data.get("missions", [])
                
                if count == 0:
                    return "The agency is currently idle. There are no active or queued missions."
                
                output = f"The agency has {count} active missions:\n"
                for m in missions:
                    output += f"- Mission #{m['id']}: {m['name']} (Studio: {m['studio']}, Status: {m['status']})\n"
                return output
            return f"Error: API returned status code {r.status_code}"
        except Exception as e:
            return f"Error connecting to Agency OS: {e}"

@mcp.tool()
async def get_recent_missions(limit: int = 5) -> str:
    """Get the status of recently completed or failed missions. Use this when the user asks 'what did the agency just finish?', 'show me the results of the last task', or 'did my objective complete?'"""
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"http://localhost:8080/api/missions/recent?limit={limit}", timeout=5)
            if r.status_code == 200:
                data = r.json()
                count = data.get("count", 0)
                missions = data.get("missions", [])
                
                if count == 0:
                    return "There are no recently finished missions."
                
                output = f"The agency recently finished {count} missions:\n"
                for m in missions:
                    output += f"- Mission #{m['id']}: {m['name']} (Studio: {m['studio']}, Status: {m['status']}, Completed: {m.get('completed_at')})\n"
                return output
            return f"Error: API returned status code {r.status_code}"
        except Exception as e:
            return f"Error connecting to Agency OS: {e}"

@mcp.tool()
async def get_mission_status(mission_id: int) -> str:
    """Get the detailed status of a specific mission by its ID. Use this when the user asks about a specific task ID."""
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"http://localhost:8080/api/mission/{mission_id}/status", timeout=5)
            if r.status_code == 404:
                return f"Mission #{mission_id} not found."
            if r.status_code == 200:
                m = r.json()
                output = (
                    f"Mission #{m.get('id')} Details:\n"
                    f"Name: {m.get('name')}\n"
                    f"Studio: {m.get('studio')}\n"
                    f"Status: {m.get('status')}\n"
                    f"Created: {m.get('created_at')}\n"
                    f"Completed: {m.get('completed_at', 'N/A')}\n"
                )
                if m.get('artifacts'):
                    output += f"Artifacts produced: {', '.join(m['artifacts'])}\n"
                return output
            return f"Error: API returned status code {r.status_code}"
        except Exception as e:
            return f"Error connecting to Agency OS: {e}"

@mcp.tool()
async def submit_mission_feedback(mission_id: int, feedback: str, action: str = "revise") -> str:
    """Submit feedback or request a revision for a completed mission.
    Use this when the user says they don't like the result, e.g. 'tell the design team to make the logo blue'.
    'action' should be 'revise' or 'approve'.
    """
    async with httpx.AsyncClient() as client:
        try:
            payload = {"action": action, "feedback": feedback, "priority": 7}
            r = await client.post(f"http://localhost:8080/api/mission/{mission_id}/feedback", json=payload, timeout=5)
            if r.status_code == 200:
                data = r.json()
                return f"Success: {data.get('message')}"
            return f"Error {r.status_code}: {r.text}"
        except Exception as e:
            return f"Error connecting to Agency OS: {e}"

@mcp.tool()
async def cancel_mission(mission_id: int) -> str:
    """Cancel a queued or running mission. Use this when the user requests to stop a task."""
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(f"http://localhost:8080/api/mission/{mission_id}/cancel", timeout=5)
            if r.status_code == 200:
                data = r.json()
                return f"Success: {data.get('status')}"
            return f"Error {r.status_code}: {r.text}"
        except Exception as e:
            return f"Error connecting to Agency OS: {e}"

@mcp.tool()
async def delegate_task(prompt: str, priority: int = 5) -> str:
    """Create a new mission objective and delegate it to the agency agents. 
    Use this when the user asks you to do complex work that requires a specific team (e.g. 'write a blog post', 'analyze this code', 'create a marketing campaign').
    """
    async with httpx.AsyncClient() as client:
        try:
            payload = {"prompt": prompt, "priority": priority}
            r = await client.post("http://localhost:8080/api/orchestrate", json=payload, timeout=10)
            if r.status_code == 200:
                data = r.json()
                return f"Success! Created {data.get('total')} missions across {len(data.get('studios', []))} studios. Objective: {data.get('objective')}"
            return f"Error {r.status_code}: {r.text}"
        except Exception as e:
            return f"Error connecting to Agency OS: {e}"

if __name__ == "__main__":
    mcp.run(transport='stdio')
