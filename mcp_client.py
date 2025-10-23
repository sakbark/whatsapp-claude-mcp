"""
MCP Client Integration
Connects to MCP servers and executes tool calls from Claude
"""

import os
import asyncio
import json
import logging
from typing import List, Dict, Any, Optional
from anthropic import Anthropic
from anthropic.types import Message, TextBlock, ToolUseBlock

logger = logging.getLogger(__name__)


class MCPClient:
    """
    Simple MCP client that connects to configured MCP servers
    Starts with Todoist, will expand to Gmail, Calendar, etc.
    """

    def __init__(self):
        self.anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.available_tools = []
        self.mcp_servers = {}

    async def initialize(self):
        """Initialize connections to MCP servers"""
        # For now, we'll use the Todoist API directly
        # Later we'll connect to actual MCP servers via stdio
        logger.info("Initializing MCP client...")

        # Load Todoist credentials from env
        self.todoist_token = os.getenv("TODOIST_API_TOKEN")

        if self.todoist_token:
            # Define Todoist tools for Claude
            self.available_tools = self._get_todoist_tools()
            logger.info(f"Loaded {len(self.available_tools)} Todoist tools")
        else:
            logger.warning("No Todoist token found, MCP features will be limited")

    def _get_todoist_tools(self) -> List[Dict[str, Any]]:
        """Define Todoist tools for Claude"""
        return [
            {
                "name": "todoist_get_tasks",
                "description": "Get tasks from Todoist. Can filter by project, label, or get all tasks.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filter": {
                            "type": "string",
                            "description": "Optional filter like 'today', 'overdue', or a project name"
                        }
                    }
                }
            },
            {
                "name": "todoist_create_task",
                "description": "Create a new task in Todoist",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The task content/title"
                        },
                        "due_string": {
                            "type": "string",
                            "description": "Natural language due date like 'tomorrow', 'next monday', 'in 3 days'"
                        },
                        "priority": {
                            "type": "integer",
                            "description": "Priority from 1 (lowest) to 4 (highest)"
                        }
                    },
                    "required": ["content"]
                }
            },
            {
                "name": "todoist_complete_task",
                "description": "Mark a task as complete in Todoist",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "The ID of the task to complete"
                        }
                    },
                    "required": ["task_id"]
                }
            }
        ]

    async def execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call via MCP"""
        logger.info(f"Executing tool: {tool_name} with input: {tool_input}")

        try:
            if tool_name == "todoist_get_tasks":
                return await self._todoist_get_tasks(tool_input.get("filter"))
            elif tool_name == "todoist_create_task":
                return await self._todoist_create_task(tool_input)
            elif tool_name == "todoist_complete_task":
                return await self._todoist_complete_task(tool_input.get("task_id"))
            else:
                return {"error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {str(e)}", exc_info=True)
            return {"error": str(e)}

    async def _todoist_get_tasks(self, filter_str: Optional[str] = None) -> Dict[str, Any]:
        """Get tasks from Todoist API"""
        import aiohttp

        url = "https://api.todoist.com/rest/v2/tasks"
        headers = {"Authorization": f"Bearer {self.todoist_token}"}

        params = {}
        if filter_str:
            params["filter"] = filter_str

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    tasks = await response.json()
                    return {
                        "success": True,
                        "tasks": tasks,
                        "count": len(tasks)
                    }
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"Todoist API error: {response.status} - {error_text}"
                    }

    async def _todoist_create_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a task in Todoist"""
        import aiohttp

        url = "https://api.todoist.com/rest/v2/tasks"
        headers = {
            "Authorization": f"Bearer {self.todoist_token}",
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=task_data) as response:
                if response.status in [200, 201]:
                    task = await response.json()
                    return {
                        "success": True,
                        "task": task,
                        "message": f"Created task: {task['content']}"
                    }
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"Todoist API error: {response.status} - {error_text}"
                    }

    async def _todoist_complete_task(self, task_id: str) -> Dict[str, Any]:
        """Complete a task in Todoist"""
        import aiohttp

        url = f"https://api.todoist.com/rest/v2/tasks/{task_id}/close"
        headers = {"Authorization": f"Bearer {self.todoist_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as response:
                if response.status == 204:
                    return {
                        "success": True,
                        "message": f"Task {task_id} marked as complete"
                    }
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"Todoist API error: {response.status} - {error_text}"
                    }

    async def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        max_turns: int = 5
    ) -> str:
        """
        Chat with Claude using MCP tools
        Handles the tool execution loop automatically
        """

        current_messages = messages.copy()

        for turn in range(max_turns):
            logger.info(f"Tool execution turn {turn + 1}/{max_turns}")

            # Call Claude with available tools
            response = self.anthropic_client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=2048,
                system=system_prompt,
                messages=current_messages,
                tools=self.available_tools if self.available_tools else None
            )

            logger.info(f"Claude response: stop_reason={response.stop_reason}")

            # Check if Claude wants to use tools
            if response.stop_reason == "tool_use":
                # Extract tool calls
                tool_results = []

                for content_block in response.content:
                    if isinstance(content_block, ToolUseBlock):
                        tool_name = content_block.name
                        tool_input = content_block.input
                        tool_use_id = content_block.id

                        logger.info(f"Claude wants to use tool: {tool_name}")

                        # Execute the tool
                        result = await self.execute_tool(tool_name, tool_input)

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": json.dumps(result)
                        })

                # Add assistant message and tool results to conversation
                current_messages.append({
                    "role": "assistant",
                    "content": response.content
                })
                current_messages.append({
                    "role": "user",
                    "content": tool_results
                })

                # Continue the loop to get Claude's final response
                continue

            else:
                # Claude has finished, return the final text response
                text_content = ""
                for content_block in response.content:
                    if isinstance(content_block, TextBlock):
                        text_content += content_block.text

                return text_content

        # If we hit max turns, return what we have
        logger.warning(f"Hit max turns ({max_turns}) in tool execution loop")
        return "I apologize, but I'm having trouble completing that request. Please try again."


# Global MCP client instance
mcp_client = MCPClient()
