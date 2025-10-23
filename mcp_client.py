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
        self.anthropic_client = None  # Will be initialized in initialize()
        self.available_tools = []
        self.mcp_servers = {}

    async def initialize(self):
        """Initialize connections to MCP servers"""
        # For now, we'll use APIs directly
        # Later we'll connect to actual MCP servers via stdio
        logger.info("Initializing MCP client...")

        # Load Anthropic API key from GSM
        anthropic_key = await self._get_secret("anthropic-api-key")
        if not anthropic_key:
            anthropic_key = os.getenv("ANTHROPIC_API_KEY")
            if anthropic_key:
                logger.info("Using Anthropic API key from environment variable")

        if anthropic_key:
            self.anthropic_client = Anthropic(api_key=anthropic_key)
            logger.info("✅ Anthropic client initialized in MCP client")
        else:
            logger.error("❌ Anthropic API key not found - MCP client will not work")

        # Load credentials - try Secret Manager first, fallback to env
        self.todoist_token = os.getenv("TODOIST_API_TOKEN")
        self.google_user_email = os.getenv("GOOGLE_USER_EMAIL", "saad@sakbark.com")

        # Try to get both Google OAuth tokens from Secret Manager
        self.google_oauth_token_work = await self._get_secret("google-oauth-token-work")
        self.google_oauth_token_personal = await self._get_secret("google-oauth-token-personal")

        # Default to work account
        self.current_google_account = "work"
        self.google_oauth_token = self.google_oauth_token_work

        # Fallback to environment variable if no work token
        if not self.google_oauth_token:
            self.google_oauth_token = os.getenv("GOOGLE_OAUTH_TOKEN")
            if self.google_oauth_token:
                logger.info("Using Google OAuth token from environment variable")
        else:
            logger.info(f"Using Google OAuth token from Secret Manager (account: {self.current_google_account})")
            if self.google_oauth_token_personal:
                logger.info("Personal Google account also available")

        # Load Google Maps and Custom Search credentials
        self.google_maps_api_key = await self._get_secret("google-maps-api-key")
        if not self.google_maps_api_key:
            self.google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")

        self.google_custom_search_api_key = await self._get_secret("google-custom-search-api-key")
        if not self.google_custom_search_api_key:
            self.google_custom_search_api_key = os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")

        self.google_custom_search_engine_id = await self._get_secret("google-custom-search-cx")
        if not self.google_custom_search_engine_id:
            self.google_custom_search_engine_id = os.getenv("GOOGLE_CUSTOM_SEARCH_ENGINE_ID")

        # Build available tools list
        self.available_tools = []

        if self.todoist_token:
            self.available_tools.extend(self._get_todoist_tools())
            logger.info(f"Loaded {len(self._get_todoist_tools())} Todoist tools")

        if self.google_oauth_token:
            self.available_tools.extend(self._get_gmail_tools())
            self.available_tools.extend(self._get_calendar_tools())
            logger.info(f"Loaded Gmail and Calendar tools")

        if self.google_maps_api_key:
            self.available_tools.extend(self._get_google_maps_tools())
            logger.info(f"Loaded {len(self._get_google_maps_tools())} Google Maps tools")

        if self.google_custom_search_api_key and self.google_custom_search_engine_id:
            self.available_tools.extend(self._get_web_search_tools())
            logger.info(f"Loaded {len(self._get_web_search_tools())} web search tools")

        logger.info(f"Total tools available: {len(self.available_tools)}")

    def _get_active_google_token(self) -> str:
        """
        Get the appropriate Google OAuth token based on active account.
        Falls back to work token if active_account not set.
        """
        active = getattr(self, 'active_account', 'personal')

        if active == "work":
            token = self.google_oauth_token_work
            logger.debug("Using work Google account")
        else:
            token = self.google_oauth_token_personal
            logger.debug("Using personal Google account")

        # Fallback chain if selected account token not available
        if not token:
            logger.warning(f"{active} account token not available, falling back to work")
            token = self.google_oauth_token_work

        if not token:
            logger.warning("Work token not available, falling back to legacy token")
            token = self.google_oauth_token

        return token

    def _get_todoist_tools(self) -> List[Dict[str, Any]]:
        """Define Todoist tools for Claude"""
        return [
            {
                "name": "todoist_get_tasks",
                "description": "Get tasks from Todoist with comprehensive filtering options. Supports project, label, priority, and due date filters.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filter": {
                            "type": "string",
                            "description": "Todoist filter query (e.g., 'today', 'overdue', 'p1', 'due before: tomorrow', '@label_name', '#project_name')"
                        },
                        "project_id": {
                            "type": "string",
                            "description": "Filter by specific project ID"
                        },
                        "label": {
                            "type": "string",
                            "description": "Filter by label name"
                        },
                        "priority": {
                            "type": "integer",
                            "description": "Filter by priority (1-4, where 4 is highest)"
                        }
                    }
                }
            },
            {
                "name": "todoist_create_task",
                "description": "Create a new task in Todoist with full support for labels, projects, sections, subtasks, descriptions",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The task content/title"
                        },
                        "description": {
                            "type": "string",
                            "description": "Task description/notes"
                        },
                        "project_id": {
                            "type": "string",
                            "description": "Project ID to add task to"
                        },
                        "section_id": {
                            "type": "string",
                            "description": "Section ID within project"
                        },
                        "parent_id": {
                            "type": "string",
                            "description": "Parent task ID for creating subtasks"
                        },
                        "labels": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Array of label names to add"
                        },
                        "due_string": {
                            "type": "string",
                            "description": "Natural language due date like 'tomorrow', 'next monday', 'every monday' for recurring"
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
            },
            {
                "name": "todoist_update_task",
                "description": "Update an existing task in Todoist (content, description, due date, priority, labels, etc.)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "The ID of the task to update"},
                        "content": {"type": "string", "description": "New task content/title"},
                        "description": {"type": "string", "description": "New task description/notes"},
                        "due_string": {"type": "string", "description": "New due date in natural language"},
                        "priority": {"type": "integer", "description": "Priority from 1-4"},
                        "labels": {"type": "array", "items": {"type": "string"}, "description": "Array of label names"}
                    },
                    "required": ["task_id"]
                }
            },
            {
                "name": "todoist_delete_task",
                "description": "Delete a task from Todoist permanently",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "The ID of the task to delete"}
                    },
                    "required": ["task_id"]
                }
            },
            {
                "name": "todoist_list_projects",
                "description": "List all projects in Todoist",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]

    def _get_gmail_tools(self) -> List[Dict[str, Any]]:
        """Define Gmail tools for Claude"""
        return [
            {
                "name": "gmail_search",
                "description": "Search Gmail messages. Returns recent emails matching the query.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Gmail search query (e.g., 'from:someone@email.com', 'is:unread', 'subject:invoice')"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of emails to return (default: 10)"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "gmail_send",
                "description": "Send an email via Gmail",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient email address"},
                        "subject": {"type": "string", "description": "Email subject"},
                        "body": {"type": "string", "description": "Email body text"}
                    },
                    "required": ["to", "subject", "body"]
                }
            },
            {
                "name": "gmail_read",
                "description": "Read full content of a specific email by ID",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "Email message ID from search results"}
                    },
                    "required": ["message_id"]
                }
            },
            {
                "name": "gmail_reply",
                "description": "Reply to an email (maintains thread)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "ID of message to reply to"},
                        "body": {"type": "string", "description": "Reply body text"}
                    },
                    "required": ["message_id", "body"]
                }
            },
            {
                "name": "gmail_delete",
                "description": "Move email to trash",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "Email message ID"}
                    },
                    "required": ["message_id"]
                }
            },
            {
                "name": "gmail_archive",
                "description": "Archive an email (remove from inbox)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "Email message ID"}
                    },
                    "required": ["message_id"]
                }
            },
            {
                "name": "gmail_mark_read",
                "description": "Mark email as read or unread",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "Email message ID"},
                        "read": {"type": "boolean", "description": "True to mark as read, false for unread"}
                    },
                    "required": ["message_id", "read"]
                }
            },
            {
                "name": "gmail_list_labels",
                "description": "List all Gmail labels/folders",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "gmail_create_label",
                "description": "Create a new Gmail label/folder",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Label name"}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "gmail_delete_label",
                "description": "Delete a Gmail label/folder",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "label_id": {"type": "string", "description": "Label ID to delete"}
                    },
                    "required": ["label_id"]
                }
            },
            {
                "name": "gmail_update_label",
                "description": "Update/rename a Gmail label",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "label_id": {"type": "string", "description": "Label ID to update"},
                        "name": {"type": "string", "description": "New label name"}
                    },
                    "required": ["label_id", "name"]
                }
            },
            {
                "name": "gmail_add_label",
                "description": "Add a label to an email message",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "Email message ID"},
                        "label_id": {"type": "string", "description": "Label ID to add"}
                    },
                    "required": ["message_id", "label_id"]
                }
            },
            {
                "name": "gmail_remove_label",
                "description": "Remove a label from an email message",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "Email message ID"},
                        "label_id": {"type": "string", "description": "Label ID to remove"}
                    },
                    "required": ["message_id", "label_id"]
                }
            }
        ]

    def _get_calendar_tools(self) -> List[Dict[str, Any]]:
        """Define Calendar tools for Claude"""
        return [
            {
                "name": "calendar_list_events",
                "description": "List upcoming calendar events. Shows events for today and the next 7 days by default.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days_ahead": {
                            "type": "integer",
                            "description": "Number of days to look ahead (default: 7)"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of events to return (default: 10)"
                        }
                    }
                }
            },
            {
                "name": "calendar_create_event",
                "description": "Create a new calendar event",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "Event title/summary"},
                        "start_time": {"type": "string", "description": "Start time in ISO format (e.g., '2024-10-23T14:00:00')"},
                        "end_time": {"type": "string", "description": "End time in ISO format"},
                        "description": {"type": "string", "description": "Event description (optional)"},
                        "location": {"type": "string", "description": "Event location (optional)"},
                        "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of attendee emails (optional)"}
                    },
                    "required": ["summary", "start_time", "end_time"]
                }
            },
            {
                "name": "calendar_update_event",
                "description": "Update an existing calendar event",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string", "description": "Event ID to update"},
                        "summary": {"type": "string", "description": "New event title"},
                        "start_time": {"type": "string", "description": "New start time in ISO format"},
                        "end_time": {"type": "string", "description": "New end time in ISO format"},
                        "description": {"type": "string", "description": "New description"},
                        "location": {"type": "string", "description": "New location"}
                    },
                    "required": ["event_id"]
                }
            },
            {
                "name": "calendar_delete_event",
                "description": "Delete a calendar event",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string", "description": "Event ID to delete"}
                    },
                    "required": ["event_id"]
                }
            },
            {
                "name": "calendar_list_calendars",
                "description": "List all available calendars",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            },

            # ===== NEW TODOIST FEATURES =====
            {
                "name": "todoist_list_labels",
                "description": "List all Todoist labels",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "todoist_create_label",
                "description": "Create a new label in Todoist",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Label name"},
                        "color": {"type": "string", "description": "Color name (e.g., 'red', 'blue', 'green')"}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "todoist_create_project",
                "description": "Create a new project in Todoist",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Project name"},
                        "color": {"type": "string", "description": "Color name (optional)"},
                        "favorite": {"type": "boolean", "description": "Mark as favorite (optional)"}
                    },
                    "required": ["name"]
                }
            },
            {
                "name": "todoist_update_project",
                "description": "Update an existing Todoist project",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "name": {"type": "string", "description": "New name (optional)"},
                        "color": {"type": "string", "description": "New color (optional)"},
                        "favorite": {"type": "boolean", "description": "Favorite status (optional)"}
                    },
                    "required": ["project_id"]
                }
            },
            {
                "name": "todoist_delete_project",
                "description": "Delete a Todoist project",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID to delete"}
                    },
                    "required": ["project_id"]
                }
            },
            {
                "name": "todoist_list_sections",
                "description": "List sections in a Todoist project",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"}
                    },
                    "required": ["project_id"]
                }
            },
            {
                "name": "todoist_create_section",
                "description": "Create a section in a Todoist project",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "name": {"type": "string", "description": "Section name"}
                    },
                    "required": ["project_id", "name"]
                }
            },
            {
                "name": "todoist_add_comment",
                "description": "Add a comment to a Todoist task",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task ID"},
                        "content": {"type": "string", "description": "Comment text"}
                    },
                    "required": ["task_id", "content"]
                }
            },
            {
                "name": "todoist_list_comments",
                "description": "List comments for a Todoist task",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task ID"}
                    },
                    "required": ["task_id"]
                }
            },

            # ===== NEW GMAIL FEATURES =====
            {
                "name": "gmail_send_advanced",
                "description": "Send email with CC/BCC, HTML, and attachments",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient email"},
                        "subject": {"type": "string", "description": "Email subject"},
                        "body": {"type": "string", "description": "Email body (text or HTML)"},
                        "cc": {"type": "string", "description": "CC recipients (comma-separated)"},
                        "bcc": {"type": "string", "description": "BCC recipients (comma-separated)"},
                        "html": {"type": "boolean", "description": "Is body HTML? (default: false)"},
                        "attachment_paths": {"type": "array", "items": {"type": "string"}, "description": "Local file paths to attach"}
                    },
                    "required": ["to", "subject", "body"]
                }
            },
            {
                "name": "gmail_download_attachment",
                "description": "Download email attachment to local file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message_id": {"type": "string", "description": "Email message ID"},
                        "attachment_id": {"type": "string", "description": "Attachment ID"},
                        "filename": {"type": "string", "description": "Save as filename"}
                    },
                    "required": ["message_id", "attachment_id", "filename"]
                }
            },
            {
                "name": "gmail_create_draft",
                "description": "Create an email draft",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient"},
                        "subject": {"type": "string", "description": "Subject"},
                        "body": {"type": "string", "description": "Body text"}
                    },
                    "required": ["to", "subject", "body"]
                }
            },
            {
                "name": "gmail_list_drafts",
                "description": "List email drafts",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "max_results": {"type": "integer", "description": "Max drafts to return (default: 10)"}
                    }
                }
            },
            {
                "name": "gmail_send_draft",
                "description": "Send an existing draft",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string", "description": "Draft ID to send"}
                    },
                    "required": ["draft_id"]
                }
            },
            {
                "name": "gmail_get_thread",
                "description": "Get full email thread/conversation",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "thread_id": {"type": "string", "description": "Thread ID"}
                    },
                    "required": ["thread_id"]
                }
            },

            # ===== NEW CALENDAR FEATURES =====
            {
                "name": "calendar_create_event_advanced",
                "description": "Create event with Google Meet, recurring, all-day, multiple calendars",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "Event title"},
                        "start_time": {"type": "string", "description": "Start time ISO format or date for all-day"},
                        "end_time": {"type": "string", "description": "End time ISO format or date for all-day"},
                        "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                        "description": {"type": "string", "description": "Description"},
                        "location": {"type": "string", "description": "Location"},
                        "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee emails"},
                        "add_meet": {"type": "boolean", "description": "Add Google Meet link"},
                        "all_day": {"type": "boolean", "description": "All-day event"},
                        "timezone": {"type": "string", "description": "Timezone (e.g., 'Europe/London')"},
                        "recurrence": {"type": "array", "items": {"type": "string"}, "description": "RRULE recurrence rules"},
                        "color_id": {"type": "string", "description": "Event color (1-11)"},
                        "reminders": {"type": "array", "items": {"type": "object"}, "description": "Custom reminders"}
                    },
                    "required": ["summary", "start_time", "end_time"]
                }
            },
            {
                "name": "calendar_search_events",
                "description": "Search calendar events by keyword",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"},
                        "max_results": {"type": "integer", "description": "Max results (default: 10)"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "calendar_check_free_busy",
                "description": "Check free/busy status for time range",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "start_time": {"type": "string", "description": "Start time ISO format"},
                        "end_time": {"type": "string", "description": "End time ISO format"},
                        "calendar_ids": {"type": "array", "items": {"type": "string"}, "description": "Calendar IDs to check"}
                    },
                    "required": ["start_time", "end_time"]
                }
            },

            # ===== ADDITIONAL TODOIST CRUD =====
            {
                "name": "todoist_update_label",
                "description": "Update an existing Todoist label",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "label_id": {"type": "string", "description": "Label ID to update"},
                        "name": {"type": "string", "description": "New label name"},
                        "color": {"type": "string", "description": "New color name"}
                    },
                    "required": ["label_id"]
                }
            },
            {
                "name": "todoist_delete_label",
                "description": "Delete a Todoist label",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "label_id": {"type": "string", "description": "Label ID to delete"}
                    },
                    "required": ["label_id"]
                }
            },
            {
                "name": "todoist_update_section",
                "description": "Update an existing Todoist section",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "section_id": {"type": "string", "description": "Section ID to update"},
                        "name": {"type": "string", "description": "New section name"}
                    },
                    "required": ["section_id", "name"]
                }
            },
            {
                "name": "todoist_delete_section",
                "description": "Delete a Todoist section",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "section_id": {"type": "string", "description": "Section ID to delete"}
                    },
                    "required": ["section_id"]
                }
            },
            {
                "name": "todoist_update_comment",
                "description": "Update an existing task comment",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "comment_id": {"type": "string", "description": "Comment ID to update"},
                        "content": {"type": "string", "description": "New comment content"}
                    },
                    "required": ["comment_id", "content"]
                }
            },
            {
                "name": "todoist_delete_comment",
                "description": "Delete a task comment",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "comment_id": {"type": "string", "description": "Comment ID to delete"}
                    },
                    "required": ["comment_id"]
                }
            },

            # ===== ADDITIONAL GMAIL FEATURES =====
            {
                "name": "gmail_delete_draft",
                "description": "Delete a Gmail draft",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "draft_id": {"type": "string", "description": "Draft ID to delete"}
                    },
                    "required": ["draft_id"]
                }
            },
            {
                "name": "gmail_create_filter",
                "description": "Create a Gmail filter to automatically organize emails",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "criteria": {"type": "object", "description": "Filter criteria (from, to, subject, query, etc.)"},
                        "action": {"type": "object", "description": "Actions to take (addLabelIds, removeLabelIds, archive, delete, etc.)"}
                    },
                    "required": ["criteria", "action"]
                }
            },
            {
                "name": "gmail_list_filters",
                "description": "List all Gmail filters",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "gmail_delete_filter",
                "description": "Delete a Gmail filter",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "filter_id": {"type": "string", "description": "Filter ID to delete"}
                    },
                    "required": ["filter_id"]
                }
            },

            # ===== ADDITIONAL CALENDAR FEATURES =====
            {
                "name": "calendar_add_attendee",
                "description": "Add an attendee to a calendar event",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string", "description": "Event ID"},
                        "email": {"type": "string", "description": "Attendee email address"},
                        "optional": {"type": "boolean", "description": "Whether attendee is optional (default: false)"},
                        "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"}
                    },
                    "required": ["event_id", "email"]
                }
            },
            {
                "name": "calendar_remove_attendee",
                "description": "Remove an attendee from a calendar event",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string", "description": "Event ID"},
                        "email": {"type": "string", "description": "Attendee email address to remove"},
                        "calendar_id": {"type": "string", "description": "Calendar ID (default: primary)"}
                    },
                    "required": ["event_id", "email"]
                }
            }
        ]

    def _get_google_maps_tools(self) -> List[Dict[str, Any]]:
        """Define Google Maps tools for Claude"""
        return [
            {
                "name": "google_maps_search_places",
                "description": "Search for places using Google Maps Places API. Find restaurants, businesses, landmarks, addresses, etc.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (e.g., 'pizza near me', 'Eiffel Tower', 'coffee shops in London')"
                        },
                        "location": {
                            "type": "string",
                            "description": "Location bias (e.g., 'London, UK', 'lat,lng coordinates')"
                        },
                        "radius": {
                            "type": "integer",
                            "description": "Search radius in meters (default: 5000)"
                        },
                        "type": {
                            "type": "string",
                            "description": "Place type filter (e.g., 'restaurant', 'cafe', 'hotel', 'museum')"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "google_maps_get_directions",
                "description": "Get directions between two locations using Google Maps Directions API",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "origin": {
                            "type": "string",
                            "description": "Starting location (address or 'lat,lng')"
                        },
                        "destination": {
                            "type": "string",
                            "description": "Destination location (address or 'lat,lng')"
                        },
                        "mode": {
                            "type": "string",
                            "description": "Travel mode: driving, walking, bicycling, transit (default: driving)",
                            "enum": ["driving", "walking", "bicycling", "transit"]
                        },
                        "departure_time": {
                            "type": "string",
                            "description": "Departure time for transit (ISO format or 'now')"
                        },
                        "alternatives": {
                            "type": "boolean",
                            "description": "Return alternative routes (default: false)"
                        }
                    },
                    "required": ["origin", "destination"]
                }
            },
            {
                "name": "google_maps_get_place_details",
                "description": "Get detailed information about a specific place (hours, phone, website, reviews, etc.)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "place_id": {
                            "type": "string",
                            "description": "Google Place ID (from search results)"
                        },
                        "fields": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific fields to retrieve (e.g., ['opening_hours', 'rating', 'phone', 'website'])"
                        }
                    },
                    "required": ["place_id"]
                }
            }
        ]

    def _get_web_search_tools(self) -> List[Dict[str, Any]]:
        """Define web search tools for Claude"""
        return [
            {
                "name": "google_web_search",
                "description": "Search the web using Google Custom Search API. Returns web pages, news, images related to query.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (e.g., 'latest news on AI', 'how to cook pasta')"
                        },
                        "num_results": {
                            "type": "integer",
                            "description": "Number of results to return (1-10, default: 5)"
                        },
                        "search_type": {
                            "type": "string",
                            "description": "Type of search: web, image (default: web)",
                            "enum": ["web", "image"]
                        },
                        "site": {
                            "type": "string",
                            "description": "Restrict search to specific site (e.g., 'reddit.com', 'github.com')"
                        },
                        "date_restrict": {
                            "type": "string",
                            "description": "Restrict to recent content (e.g., 'd7' for past week, 'm1' for past month)"
                        }
                    },
                    "required": ["query"]
                }
            }
        ]

    async def execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call via MCP"""
        logger.info(f"Executing tool: {tool_name} with input: {tool_input}")

        try:
            if tool_name == "todoist_get_tasks":
                return await self._todoist_get_tasks(tool_input)
            elif tool_name == "todoist_create_task":
                return await self._todoist_create_task(tool_input)
            elif tool_name == "todoist_complete_task":
                return await self._todoist_complete_task(tool_input.get("task_id"))
            elif tool_name == "todoist_update_task":
                return await self._todoist_update_task(tool_input)
            elif tool_name == "todoist_delete_task":
                return await self._todoist_delete_task(tool_input.get("task_id"))
            elif tool_name == "todoist_list_projects":
                return await self._todoist_list_projects()
            elif tool_name == "gmail_search":
                return await self._gmail_search(tool_input)
            elif tool_name == "gmail_send":
                return await self._gmail_send(tool_input)
            elif tool_name == "gmail_read":
                return await self._gmail_read(tool_input.get("message_id"))
            elif tool_name == "gmail_reply":
                return await self._gmail_reply(tool_input)
            elif tool_name == "gmail_delete":
                return await self._gmail_delete(tool_input.get("message_id"))
            elif tool_name == "gmail_archive":
                return await self._gmail_archive(tool_input.get("message_id"))
            elif tool_name == "gmail_mark_read":
                return await self._gmail_mark_read(tool_input)
            elif tool_name == "gmail_list_labels":
                return await self._gmail_list_labels()
            elif tool_name == "gmail_create_label":
                return await self._gmail_create_label(tool_input.get("name"))
            elif tool_name == "gmail_delete_label":
                return await self._gmail_delete_label(tool_input.get("label_id"))
            elif tool_name == "gmail_update_label":
                return await self._gmail_update_label(tool_input)
            elif tool_name == "gmail_add_label":
                return await self._gmail_add_label(tool_input)
            elif tool_name == "gmail_remove_label":
                return await self._gmail_remove_label(tool_input)
            elif tool_name == "calendar_list_events":
                return await self._calendar_list_events(tool_input)
            elif tool_name == "calendar_create_event":
                return await self._calendar_create_event(tool_input)
            elif tool_name == "calendar_update_event":
                return await self._calendar_update_event(tool_input)
            elif tool_name == "calendar_delete_event":
                return await self._calendar_delete_event(tool_input.get("event_id"))
            elif tool_name == "calendar_list_calendars":
                return await self._calendar_list_calendars()

            # New Todoist features
            elif tool_name == "todoist_list_labels":
                return await self._todoist_list_labels()
            elif tool_name == "todoist_create_label":
                return await self._todoist_create_label(tool_input)
            elif tool_name == "todoist_create_project":
                return await self._todoist_create_project(tool_input)
            elif tool_name == "todoist_update_project":
                return await self._todoist_update_project(tool_input)
            elif tool_name == "todoist_delete_project":
                return await self._todoist_delete_project(tool_input.get("project_id"))
            elif tool_name == "todoist_list_sections":
                return await self._todoist_list_sections(tool_input.get("project_id"))
            elif tool_name == "todoist_create_section":
                return await self._todoist_create_section(tool_input)
            elif tool_name == "todoist_add_comment":
                return await self._todoist_add_comment(tool_input)
            elif tool_name == "todoist_list_comments":
                return await self._todoist_list_comments(tool_input.get("task_id"))

            # New Gmail features
            elif tool_name == "gmail_send_advanced":
                return await self._gmail_send_advanced(tool_input)
            elif tool_name == "gmail_download_attachment":
                return await self._gmail_download_attachment(tool_input)
            elif tool_name == "gmail_create_draft":
                return await self._gmail_create_draft(tool_input)
            elif tool_name == "gmail_list_drafts":
                return await self._gmail_list_drafts(tool_input.get("max_results", 10))
            elif tool_name == "gmail_send_draft":
                return await self._gmail_send_draft(tool_input.get("draft_id"))
            elif tool_name == "gmail_get_thread":
                return await self._gmail_get_thread(tool_input.get("thread_id"))

            # New Calendar features
            elif tool_name == "calendar_create_event_advanced":
                return await self._calendar_create_event_advanced(tool_input)
            elif tool_name == "calendar_search_events":
                return await self._calendar_search_events(tool_input)
            elif tool_name == "calendar_check_free_busy":
                return await self._calendar_check_free_busy(tool_input)

            # Additional Todoist CRUD
            elif tool_name == "todoist_update_label":
                return await self._todoist_update_label(tool_input)
            elif tool_name == "todoist_delete_label":
                return await self._todoist_delete_label(tool_input.get("label_id"))
            elif tool_name == "todoist_update_section":
                return await self._todoist_update_section(tool_input)
            elif tool_name == "todoist_delete_section":
                return await self._todoist_delete_section(tool_input.get("section_id"))
            elif tool_name == "todoist_update_comment":
                return await self._todoist_update_comment(tool_input)
            elif tool_name == "todoist_delete_comment":
                return await self._todoist_delete_comment(tool_input.get("comment_id"))

            # Additional Gmail features
            elif tool_name == "gmail_delete_draft":
                return await self._gmail_delete_draft(tool_input.get("draft_id"))
            elif tool_name == "gmail_create_filter":
                return await self._gmail_create_filter(tool_input)
            elif tool_name == "gmail_list_filters":
                return await self._gmail_list_filters()
            elif tool_name == "gmail_delete_filter":
                return await self._gmail_delete_filter(tool_input.get("filter_id"))

            # Additional Calendar features
            elif tool_name == "calendar_add_attendee":
                return await self._calendar_add_attendee(tool_input)
            elif tool_name == "calendar_remove_attendee":
                return await self._calendar_remove_attendee(tool_input)

            # Google Maps tools
            elif tool_name == "google_maps_search_places":
                return await self._google_maps_search_places(tool_input)
            elif tool_name == "google_maps_get_directions":
                return await self._google_maps_get_directions(tool_input)
            elif tool_name == "google_maps_get_place_details":
                return await self._google_maps_get_place_details(tool_input)

            # Web search tools
            elif tool_name == "google_web_search":
                return await self._google_web_search(tool_input)

            else:
                return {"error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {str(e)}", exc_info=True)
            return {"error": str(e)}

    async def _todoist_get_tasks(self, filter_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get tasks from Todoist API with comprehensive filtering"""
        import aiohttp

        url = "https://api.todoist.com/rest/v2/tasks"
        headers = {"Authorization": f"Bearer {self.todoist_token}"}

        # Build query parameters from filter options
        params = {}

        if filter_params:
            # Support Todoist filter query syntax
            if "filter" in filter_params:
                params["filter"] = filter_params["filter"]

            # Support direct API parameters
            if "project_id" in filter_params:
                params["project_id"] = filter_params["project_id"]

            if "label" in filter_params:
                params["label"] = filter_params["label"]

            if "priority" in filter_params:
                # Todoist API expects priority 1-4
                params["priority"] = filter_params["priority"]

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

    async def _todoist_update_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a task in Todoist"""
        import aiohttp

        task_id = task_data.get("task_id")
        url = f"https://api.todoist.com/rest/v2/tasks/{task_id}"
        headers = {
            "Authorization": f"Bearer {self.todoist_token}",
            "Content-Type": "application/json"
        }

        # Build update payload
        update_data = {}
        if "content" in task_data:
            update_data["content"] = task_data["content"]
        if "description" in task_data:
            update_data["description"] = task_data["description"]
        if "due_string" in task_data:
            update_data["due_string"] = task_data["due_string"]
        if "priority" in task_data:
            update_data["priority"] = task_data["priority"]
        if "labels" in task_data:
            update_data["labels"] = task_data["labels"]

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=update_data) as response:
                if response.status == 200:
                    task = await response.json()
                    return {
                        "success": True,
                        "task": task,
                        "message": f"Updated task: {task['content']}"
                    }
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"Todoist API error: {response.status} - {error_text}"
                    }

    async def _todoist_delete_task(self, task_id: str) -> Dict[str, Any]:
        """Delete a task from Todoist"""
        import aiohttp

        url = f"https://api.todoist.com/rest/v2/tasks/{task_id}"
        headers = {"Authorization": f"Bearer {self.todoist_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as response:
                if response.status == 204:
                    return {
                        "success": True,
                        "message": f"Task {task_id} deleted"
                    }
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"Todoist API error: {response.status} - {error_text}"
                    }

    async def _todoist_list_projects(self) -> Dict[str, Any]:
        """List all projects in Todoist"""
        import aiohttp

        url = "https://api.todoist.com/rest/v2/projects"
        headers = {"Authorization": f"Bearer {self.todoist_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    projects = await response.json()
                    return {
                        "success": True,
                        "projects": projects,
                        "count": len(projects)
                    }
                else:
                    error_text = await response.text()
                    return {
                        "success": False,
                        "error": f"Todoist API error: {response.status} - {error_text}"
                    }

    async def _gmail_search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search Gmail using Google Gmail API"""
        import aiohttp
        from datetime import datetime

        query = params.get("query", "")
        max_results = params.get("max_results", 10)

        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        params_dict = {
            "q": query,
            "maxResults": min(max_results, 20)
        }

        try:
            async with aiohttp.ClientSession() as session:
                # Search for messages
                async with session.get(url, headers=headers, params=params_dict) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}

                    data = await response.json()
                    messages = data.get("messages", [])

                    if not messages:
                        return {"success": True, "emails": [], "count": 0, "message": "No emails found"}

                    # Fetch details for each message
                    email_details = []
                    for msg in messages[:max_results]:
                        msg_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}"
                        async with session.get(msg_url, headers=headers) as msg_response:
                            if msg_response.status == 200:
                                msg_data = await msg_response.json()

                                # Extract headers
                                headers_data = msg_data.get("payload", {}).get("headers", [])
                                subject = next((h["value"] for h in headers_data if h["name"] == "Subject"), "No Subject")
                                from_email = next((h["value"] for h in headers_data if h["name"] == "From"), "Unknown")
                                date = next((h["value"] for h in headers_data if h["name"] == "Date"), "Unknown")

                                # Get snippet
                                snippet = msg_data.get("snippet", "")

                                email_details.append({
                                    "id": msg["id"],
                                    "subject": subject,
                                    "from": from_email,
                                    "date": date,
                                    "snippet": snippet[:200]  # First 200 chars
                                })

                    return {
                        "success": True,
                        "emails": email_details,
                        "count": len(email_details)
                    }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _gmail_send(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send email via Gmail API"""
        import aiohttp
        import base64
        from email.mime.text import MIMEText

        to = params.get("to")
        subject = params.get("subject")
        body = params.get("body")

        try:
            # Create email message
            message = MIMEText(body)
            message['to'] = to
            message['subject'] = subject
            message['from'] = self.google_user_email

            # Encode message
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

            url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
            headers = {
                "Authorization": f"Bearer {self._get_active_google_token()}",
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json={"raw": raw_message}) as response:
                    if response.status in [200, 201]:
                        data = await response.json()
                        return {
                            "success": True,
                            "message_id": data.get("id"),
                            "message": f"Email sent to {to}"
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _gmail_read(self, message_id: str) -> Dict[str, Any]:
        """Read full email content"""
        import aiohttp

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        msg_data = await response.json()

                        # Extract headers
                        headers_data = msg_data.get("payload", {}).get("headers", [])
                        subject = next((h["value"] for h in headers_data if h["name"] == "Subject"), "No Subject")
                        from_email = next((h["value"] for h in headers_data if h["name"] == "From"), "Unknown")
                        date = next((h["value"] for h in headers_data if h["name"] == "Date"), "Unknown")

                        # Get body
                        payload = msg_data.get("payload", {})
                        body = ""

                        if "parts" in payload:
                            for part in payload["parts"]:
                                if part.get("mimeType") == "text/plain":
                                    body_data = part.get("body", {}).get("data", "")
                                    if body_data:
                                        import base64
                                        body = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')
                                        break
                        else:
                            body_data = payload.get("body", {}).get("data", "")
                            if body_data:
                                import base64
                                body = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')

                        return {
                            "success": True,
                            "id": message_id,
                            "subject": subject,
                            "from": from_email,
                            "date": date,
                            "body": body[:5000]  # Limit to first 5000 chars
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _gmail_reply(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Reply to an email with threading"""
        import aiohttp
        import base64
        from email.mime.text import MIMEText

        message_id = params.get("message_id")
        reply_body = params.get("body")

        try:
            # First get the original message to extract thread_id and headers
            get_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
            headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

            async with aiohttp.ClientSession() as session:
                async with session.get(get_url, headers=headers) as get_response:
                    if get_response.status == 200:
                        orig_msg = await get_response.json()
                        thread_id = orig_msg.get("threadId")

                        # Extract subject and recipient
                        headers_data = orig_msg.get("payload", {}).get("headers", [])
                        orig_subject = next((h["value"] for h in headers_data if h["name"] == "Subject"), "")
                        orig_from = next((h["value"] for h in headers_data if h["name"] == "From"), "")

                        # Extract email from "Name <email>" format
                        if "<" in orig_from:
                            to_email = orig_from.split("<")[1].strip(">")
                        else:
                            to_email = orig_from

                        # Create reply
                        reply = MIMEText(reply_body)
                        reply['to'] = to_email
                        reply['subject'] = f"Re: {orig_subject}" if not orig_subject.startswith("Re:") else orig_subject
                        reply['from'] = self.google_user_email
                        reply['In-Reply-To'] = message_id
                        reply['References'] = message_id

                        raw_reply = base64.urlsafe_b64encode(reply.as_bytes()).decode()

                        send_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
                        send_headers = {
                            "Authorization": f"Bearer {self._get_active_google_token()}",
                            "Content-Type": "application/json"
                        }

                        async with session.post(send_url, headers=send_headers, json={"raw": raw_reply, "threadId": thread_id}) as response:
                            if response.status in [200, 201]:
                                data = await response.json()
                                return {
                                    "success": True,
                                    "message_id": data.get("id"),
                                    "message": f"Reply sent to {to_email}"
                                }
                            else:
                                error_text = await response.text()
                                return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}
                    else:
                        error_text = await get_response.text()
                        return {"success": False, "error": f"Could not fetch original message: {get_response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _gmail_delete(self, message_id: str) -> Dict[str, Any]:
        """Move email to trash"""
        import aiohttp

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/trash"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers) as response:
                    if response.status == 200:
                        return {
                            "success": True,
                            "message": f"Email {message_id} moved to trash"
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _gmail_archive(self, message_id: str) -> Dict[str, Any]:
        """Archive email (remove from inbox)"""
        import aiohttp

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify"
        headers = {
            "Authorization": f"Bearer {self._get_active_google_token()}",
            "Content-Type": "application/json"
        }
        body = {"removeLabelIds": ["INBOX"]}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=body) as response:
                    if response.status == 200:
                        return {
                            "success": True,
                            "message": f"Email {message_id} archived"
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _gmail_mark_read(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Mark email as read or unread"""
        import aiohttp

        message_id = params.get("message_id")
        mark_read = params.get("read", True)

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify"
        headers = {
            "Authorization": f"Bearer {self._get_active_google_token()}",
            "Content-Type": "application/json"
        }

        if mark_read:
            body = {"removeLabelIds": ["UNREAD"]}
        else:
            body = {"addLabelIds": ["UNREAD"]}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=body) as response:
                    if response.status == 200:
                        status = "read" if mark_read else "unread"
                        return {
                            "success": True,
                            "message": f"Email {message_id} marked as {status}"
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _gmail_list_labels(self) -> Dict[str, Any]:
        """List all Gmail labels"""
        import aiohttp

        url = "https://gmail.googleapis.com/gmail/v1/users/me/labels"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        labels = data.get("labels", [])

                        # Format label info
                        formatted_labels = []
                        for label in labels:
                            formatted_labels.append({
                                "id": label.get("id"),
                                "name": label.get("name"),
                                "type": label.get("type"),
                                "messages_total": label.get("messagesTotal", 0),
                                "messages_unread": label.get("messagesUnread", 0)
                            })

                        return {
                            "success": True,
                            "labels": formatted_labels,
                            "count": len(formatted_labels)
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _gmail_create_label(self, name: str) -> Dict[str, Any]:
        """Create a new Gmail label"""
        import aiohttp

        url = "https://gmail.googleapis.com/gmail/v1/users/me/labels"
        headers = {
            "Authorization": f"Bearer {self._get_active_google_token()}",
            "Content-Type": "application/json"
        }

        body = {
            "name": name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=body) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "success": True,
                            "label_id": data.get("id"),
                            "label_name": data.get("name"),
                            "message": f"Created label: {name}"
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _gmail_delete_label(self, label_id: str) -> Dict[str, Any]:
        """Delete a Gmail label"""
        import aiohttp

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/labels/{label_id}"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers) as response:
                    if response.status == 204:
                        return {
                            "success": True,
                            "message": f"Label {label_id} deleted"
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _gmail_update_label(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Update/rename a Gmail label"""
        import aiohttp

        label_id = params.get("label_id")
        new_name = params.get("name")

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/labels/{label_id}"
        headers = {
            "Authorization": f"Bearer {self._get_active_google_token()}",
            "Content-Type": "application/json"
        }

        body = {"name": new_name}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=headers, json=body) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "success": True,
                            "label_id": data.get("id"),
                            "label_name": data.get("name"),
                            "message": f"Label updated to: {new_name}"
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _gmail_add_label(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a label to an email message"""
        import aiohttp

        message_id = params.get("message_id")
        label_id = params.get("label_id")

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify"
        headers = {
            "Authorization": f"Bearer {self._get_active_google_token()}",
            "Content-Type": "application/json"
        }

        body = {"addLabelIds": [label_id]}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=body) as response:
                    if response.status == 200:
                        return {
                            "success": True,
                            "message": f"Label {label_id} added to message {message_id}"
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _gmail_remove_label(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Remove a label from an email message"""
        import aiohttp

        message_id = params.get("message_id")
        label_id = params.get("label_id")

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify"
        headers = {
            "Authorization": f"Bearer {self._get_active_google_token()}",
            "Content-Type": "application/json"
        }

        body = {"removeLabelIds": [label_id]}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=body) as response:
                    if response.status == 200:
                        return {
                            "success": True,
                            "message": f"Label {label_id} removed from message {message_id}"
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _calendar_list_events(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List upcoming calendar events from owned calendars only (excludes holidays/sports)"""
        import aiohttp
        from datetime import datetime, timedelta

        days_ahead = params.get("days_ahead", 7)
        max_results = params.get("max_results", 50)  # Get more since we're filtering

        # Get time range
        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        try:
            async with aiohttp.ClientSession() as session:
                # First, get list of calendars
                calendar_list_url = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
                async with session.get(calendar_list_url, headers=headers) as cal_response:
                    if cal_response.status != 200:
                        error_text = await cal_response.text()
                        return {"success": False, "error": f"Calendar list error: {cal_response.status} - {error_text}"}

                    cal_data = await cal_response.json()

                    # Filter to only owned calendars (not holidays/sports/read-only)
                    owned_calendars = [
                        cal for cal in cal_data.get("items", [])
                        if cal.get("accessRole") in ["owner", "writer"]
                        and "holiday@" not in cal.get("id", "")
                        and "#sports@" not in cal.get("id", "")
                    ]

                    logger.info(f"Found {len(owned_calendars)} owned calendars")

                # Collect events from all owned calendars
                all_events = []
                for calendar in owned_calendars:
                    cal_id = calendar.get("id")
                    cal_name = calendar.get("summary", "Unknown")

                    events_url = f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events"
                    params_dict = {
                        "timeMin": time_min,
                        "timeMax": time_max,
                        "maxResults": max_results,
                        "singleEvents": "true",
                        "orderBy": "startTime"
                    }

                    async with session.get(events_url, headers=headers, params=params_dict) as response:
                        if response.status == 200:
                            data = await response.json()
                            events = data.get("items", [])

                            for event in events:
                                start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date"))
                                end = event.get("end", {}).get("dateTime", event.get("end", {}).get("date"))

                                all_events.append({
                                    "id": event.get("id"),
                                    "summary": event.get("summary", "No Title"),
                                    "start": start,
                                    "end": end,
                                    "calendar": cal_name,
                                    "location": event.get("location", ""),
                                    "description": event.get("description", "")[:200]
                                })

                # Sort by start time
                all_events.sort(key=lambda x: x["start"])

                # Limit to requested max_results
                limited_events = all_events[:params.get("max_results", 10)]

                if not limited_events:
                    return {"success": True, "events": [], "count": 0, "message": "No upcoming events"}

                return {
                    "success": True,
                    "events": limited_events,
                    "count": len(limited_events)
                }
        except Exception as e:
            logger.error(f"Calendar list events error: {str(e)}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def _calendar_create_event(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new calendar event"""
        import aiohttp

        summary = params.get("summary")
        start_time = params.get("start_time")
        end_time = params.get("end_time")
        description = params.get("description", "")

        event_body = {
            "summary": summary,
            "start": {"dateTime": start_time, "timeZone": "Europe/London"},
            "end": {"dateTime": end_time, "timeZone": "Europe/London"},
            "description": description
        }

        url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        headers = {
            "Authorization": f"Bearer {self._get_active_google_token()}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=event_body) as response:
                    if response.status in [200, 201]:
                        data = await response.json()
                        return {
                            "success": True,
                            "event_id": data.get("id"),
                            "html_link": data.get("htmlLink"),
                            "message": f"Event '{summary}' created"
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Calendar API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _calendar_update_event(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing calendar event"""
        import aiohttp

        event_id = params.get("event_id")
        calendar_id = params.get("calendar_id", "primary")

        # Build update payload with only provided fields
        update_body = {}

        if "summary" in params:
            update_body["summary"] = params["summary"]
        if "start_time" in params:
            update_body["start"] = {"dateTime": params["start_time"], "timeZone": "Europe/London"}
        if "end_time" in params:
            update_body["end"] = {"dateTime": params["end_time"], "timeZone": "Europe/London"}
        if "description" in params:
            update_body["description"] = params["description"]
        if "location" in params:
            update_body["location"] = params["location"]

        url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}"
        headers = {
            "Authorization": f"Bearer {self._get_active_google_token()}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=headers, json=update_body) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "success": True,
                            "event_id": data.get("id"),
                            "html_link": data.get("htmlLink"),
                            "message": f"Event updated: {data.get('summary', 'Untitled')}"
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Calendar API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _calendar_delete_event(self, event_id: str, calendar_id: str = "primary") -> Dict[str, Any]:
        """Delete a calendar event"""
        import aiohttp

        url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers) as response:
                    if response.status == 204:
                        return {
                            "success": True,
                            "message": f"Event {event_id} deleted"
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Calendar API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _calendar_list_calendars(self) -> Dict[str, Any]:
        """List all available calendars with details"""
        import aiohttp

        url = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        calendars = []

                        for cal in data.get("items", []):
                            calendars.append({
                                "id": cal.get("id"),
                                "summary": cal.get("summary", "Untitled"),
                                "description": cal.get("description", ""),
                                "access_role": cal.get("accessRole"),
                                "primary": cal.get("primary", False),
                                "timezone": cal.get("timeZone", "")
                            })

                        return {
                            "success": True,
                            "calendars": calendars,
                            "count": len(calendars)
                        }
                    else:
                        error_text = await response.text()
                        return {"success": False, "error": f"Calendar API error: {response.status} - {error_text}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =================== NEW TODOIST METHODS ===================

    async def _todoist_list_labels(self) -> Dict[str, Any]:
        """List all Todoist labels"""
        import aiohttp

        url = "https://api.todoist.com/rest/v2/labels"
        headers = {"Authorization": f"Bearer {self.todoist_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    labels = await response.json()
                    return {"success": True, "labels": labels, "count": len(labels)}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    async def _todoist_create_label(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new label"""
        import aiohttp

        url = "https://api.todoist.com/rest/v2/labels"
        headers = {"Authorization": f"Bearer {self.todoist_token}", "Content-Type": "application/json"}

        payload = {"name": params["name"]}
        if "color" in params:
            payload["color"] = params["color"]

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status in [200, 201]:
                    label = await response.json()
                    return {"success": True, "label": label}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    async def _todoist_create_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new project"""
        import aiohttp

        url = "https://api.todoist.com/rest/v2/projects"
        headers = {"Authorization": f"Bearer {self.todoist_token}", "Content-Type": "application/json"}

        payload = {"name": params["name"]}
        if "color" in params:
            payload["color"] = params["color"]
        if "favorite" in params:
            payload["is_favorite"] = params["favorite"]

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status in [200, 201]:
                    project = await response.json()
                    return {"success": True, "project": project}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    async def _todoist_update_project(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Update a project"""
        import aiohttp

        project_id = params["project_id"]
        url = f"https://api.todoist.com/rest/v2/projects/{project_id}"
        headers = {"Authorization": f"Bearer {self.todoist_token}", "Content-Type": "application/json"}

        payload = {}
        if "name" in params:
            payload["name"] = params["name"]
        if "color" in params:
            payload["color"] = params["color"]
        if "favorite" in params:
            payload["is_favorite"] = params["favorite"]

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    project = await response.json()
                    return {"success": True, "project": project}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    async def _todoist_delete_project(self, project_id: str) -> Dict[str, Any]:
        """Delete a project"""
        import aiohttp

        url = f"https://api.todoist.com/rest/v2/projects/{project_id}"
        headers = {"Authorization": f"Bearer {self.todoist_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as response:
                if response.status == 204:
                    return {"success": True}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    async def _todoist_list_sections(self, project_id: str) -> Dict[str, Any]:
        """List sections in a project"""
        import aiohttp

        url = f"https://api.todoist.com/rest/v2/sections?project_id={project_id}"
        headers = {"Authorization": f"Bearer {self.todoist_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    sections = await response.json()
                    return {"success": True, "sections": sections, "count": len(sections)}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    async def _todoist_create_section(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a section in a project"""
        import aiohttp

        url = "https://api.todoist.com/rest/v2/sections"
        headers = {"Authorization": f"Bearer {self.todoist_token}", "Content-Type": "application/json"}

        payload = {
            "name": params["name"],
            "project_id": params["project_id"]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status in [200, 201]:
                    section = await response.json()
                    return {"success": True, "section": section}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    async def _todoist_add_comment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add a comment to a task"""
        import aiohttp

        url = "https://api.todoist.com/rest/v2/comments"
        headers = {"Authorization": f"Bearer {self.todoist_token}", "Content-Type": "application/json"}

        payload = {
            "task_id": params["task_id"],
            "content": params["content"]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status in [200, 201]:
                    comment = await response.json()
                    return {"success": True, "comment": comment}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    async def _todoist_list_comments(self, task_id: str) -> Dict[str, Any]:
        """List comments for a task"""
        import aiohttp

        url = f"https://api.todoist.com/rest/v2/comments?task_id={task_id}"
        headers = {"Authorization": f"Bearer {self.todoist_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    comments = await response.json()
                    return {"success": True, "comments": comments, "count": len(comments)}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    # =================== NEW GMAIL METHODS ===================

    async def _gmail_send_advanced(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send email with CC/BCC, HTML, and attachments"""
        import aiohttp
        import base64
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders
        import os

        # Create message
        message = MIMEMultipart()
        message["to"] = params["to"]
        message["subject"] = params["subject"]

        if params.get("cc"):
            message["cc"] = params["cc"]
        if params.get("bcc"):
            message["bcc"] = params["bcc"]

        # Add body
        body_type = "html" if params.get("html") else "plain"
        message.attach(MIMEText(params["body"], body_type))

        # Add attachments if any
        if params.get("attachment_paths"):
            for file_path in params["attachment_paths"]:
                if os.path.exists(file_path):
                    with open(file_path, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(file_path)}")
                    message.attach(part)

        # Encode message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        headers = {
            "Authorization": f"Bearer {self._get_active_google_token()}",
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json={"raw": raw_message}) as response:
                if response.status == 200:
                    result = await response.json()
                    return {"success": True, "message_id": result.get("id")}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}

    async def _gmail_download_attachment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Download email attachment"""
        import aiohttp
        import base64

        message_id = params["message_id"]
        attachment_id = params["attachment_id"]
        filename = params["filename"]

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/attachments/{attachment_id}"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    file_data = base64.urlsafe_b64decode(data["data"])

                    with open(filename, "wb") as f:
                        f.write(file_data)

                    return {"success": True, "filename": filename, "size": len(file_data)}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}

    async def _gmail_create_draft(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create an email draft"""
        import aiohttp
        import base64
        from email.mime.text import MIMEText

        message = MIMEText(params["body"])
        message["to"] = params["to"]
        message["subject"] = params["subject"]

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        url = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
        headers = {
            "Authorization": f"Bearer {self._get_active_google_token()}",
            "Content-Type": "application/json"
        }

        payload = {"message": {"raw": raw_message}}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    draft = await response.json()
                    return {"success": True, "draft_id": draft.get("id")}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}

    async def _gmail_list_drafts(self, max_results: int = 10) -> Dict[str, Any]:
        """List email drafts"""
        import aiohttp

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/drafts?maxResults={max_results}"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    drafts = data.get("drafts", [])
                    return {"success": True, "drafts": drafts, "count": len(drafts)}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}

    async def _gmail_send_draft(self, draft_id: str) -> Dict[str, Any]:
        """Send an existing draft"""
        import aiohttp

        url = "https://gmail.googleapis.com/gmail/v1/users/me/drafts/send"
        headers = {
            "Authorization": f"Bearer {self._get_active_google_token()}",
            "Content-Type": "application/json"
        }

        payload = {"id": draft_id}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    return {"success": True, "message_id": result.get("id")}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}

    async def _gmail_get_thread(self, thread_id: str) -> Dict[str, Any]:
        """Get full email thread/conversation"""
        import aiohttp

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    thread = await response.json()
                    messages = thread.get("messages", [])

                    # Extract key info from each message in thread
                    thread_summary = []
                    for msg in messages:
                        headers_dict = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                        thread_summary.append({
                            "id": msg["id"],
                            "from": headers_dict.get("From", ""),
                            "subject": headers_dict.get("Subject", ""),
                            "date": headers_dict.get("Date", ""),
                            "snippet": msg.get("snippet", "")
                        })

                    return {
                        "success": True,
                        "thread_id": thread_id,
                        "messages": thread_summary,
                        "count": len(messages)
                    }
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}

    # =================== NEW CALENDAR METHODS ===================

    async def _calendar_create_event_advanced(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create event with all advanced features"""
        import aiohttp

        calendar_id = params.get("calendar_id", "primary")
        url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
        headers = {
            "Authorization": f"Bearer {self._get_active_google_token()}",
            "Content-Type": "application/json"
        }

        event = {
            "summary": params["summary"]
        }

        # Handle all-day vs timed events
        if params.get("all_day"):
            event["start"] = {"date": params["start_time"].split("T")[0]}
            event["end"] = {"date": params["end_time"].split("T")[0]}
        else:
            event["start"] = {"dateTime": params["start_time"]}
            event["end"] = {"dateTime": params["end_time"]}

            if params.get("timezone"):
                event["start"]["timeZone"] = params["timezone"]
                event["end"]["timeZone"] = params["timezone"]

        # Optional fields
        if params.get("description"):
            event["description"] = params["description"]
        if params.get("location"):
            event["location"] = params["location"]
        if params.get("attendees"):
            event["attendees"] = [{"email": email} for email in params["attendees"]]
        if params.get("recurrence"):
            event["recurrence"] = params["recurrence"]
        if params.get("color_id"):
            event["colorId"] = params["color_id"]
        if params.get("reminders"):
            event["reminders"] = {"useDefault": False, "overrides": params["reminders"]}

        # Add Google Meet
        if params.get("add_meet"):
            event["conferenceData"] = {
                "createRequest": {
                    "requestId": f"meet-{params['summary'][:10]}-{hash(params['start_time'])}"
                }
            }
            url += "?conferenceDataVersion=1"

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=event) as response:
                if response.status in [200, 201]:
                    result = await response.json()
                    return_data = {
                        "success": True,
                        "event_id": result.get("id"),
                        "html_link": result.get("htmlLink"),
                        "summary": result.get("summary")
                    }

                    # Include Google Meet link if created
                    if result.get("conferenceData"):
                        meet_link = result["conferenceData"].get("entryPoints", [{}])[0].get("uri")
                        if meet_link:
                            return_data["meet_link"] = meet_link

                    return return_data
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Calendar API error: {response.status} - {error_text}"}

    async def _calendar_search_events(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search calendar events by keyword"""
        import aiohttp

        calendar_id = params.get("calendar_id", "primary")
        query = params["query"]
        max_results = params.get("max_results", 10)

        url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        query_params = {
            "q": query,
            "maxResults": max_results,
            "singleEvents": "true",
            "orderBy": "startTime"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=query_params) as response:
                if response.status == 200:
                    data = await response.json()
                    events = []

                    for item in data.get("items", []):
                        events.append({
                            "id": item.get("id"),
                            "summary": item.get("summary", "No title"),
                            "start": item.get("start", {}).get("dateTime") or item.get("start", {}).get("date"),
                            "end": item.get("end", {}).get("dateTime") or item.get("end", {}).get("date"),
                            "location": item.get("location"),
                            "description": item.get("description")
                        })

                    return {
                        "success": True,
                        "events": events,
                        "count": len(events)
                    }
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Calendar API error: {response.status} - {error_text}"}

    async def _calendar_check_free_busy(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Check free/busy status"""
        import aiohttp

        url = "https://www.googleapis.com/calendar/v3/freeBusy"
        headers = {
            "Authorization": f"Bearer {self._get_active_google_token()}",
            "Content-Type": "application/json"
        }

        calendar_ids = params.get("calendar_ids", ["primary"])
        payload = {
            "timeMin": params["start_time"],
            "timeMax": params["end_time"],
            "items": [{"id": cal_id} for cal_id in calendar_ids]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    calendars = data.get("calendars", {})

                    result = {}
                    for cal_id, cal_data in calendars.items():
                        busy_times = cal_data.get("busy", [])
                        result[cal_id] = {
                            "busy": busy_times,
                            "is_free": len(busy_times) == 0
                        }

                    return {
                        "success": True,
                        "calendars": result
                    }
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Calendar API error: {response.status} - {error_text}"}

    async def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        max_turns: int = 5,
        active_account: str = "personal"
    ) -> str:
        """
        Chat with Claude using MCP tools
        Handles the tool execution loop automatically

        Args:
            messages: Conversation history
            system_prompt: System prompt for Claude
            max_turns: Maximum tool execution turns
            active_account: Which Google account to use ("work" or "personal")
        """

        # Store active account for use in tool execution
        self.active_account = active_account
        logger.info(f"Using {active_account} account for Google tools")

        current_messages = messages.copy()

        for turn in range(max_turns):
            logger.info(f"Tool execution turn {turn + 1}/{max_turns}")

            # Call Claude with available tools
            response = self.anthropic_client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=4096,
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

    async def _get_secret(self, secret_name: str, project_id: str = "new-fps-gpt") -> Optional[str]:
        """
        Fetch a secret from Google Secret Manager
        Returns None if secret doesn't exist or can't be accessed
        """
        try:
            from google.cloud import secretmanager

            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"

            response = client.access_secret_version(request={"name": name})
            secret_value = response.payload.data.decode("UTF-8")

            logger.info(f"Successfully retrieved secret: {secret_name}")
            return secret_value

        except Exception as e:
            logger.warning(f"Could not retrieve secret {secret_name}: {str(e)}")
            return None

    # ===== ADDITIONAL TODOIST CRUD IMPLEMENTATIONS =====

    async def _todoist_update_label(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Update a Todoist label"""
        import aiohttp

        label_id = params["label_id"]
        url = f"https://api.todoist.com/rest/v2/labels/{label_id}"
        headers = {"Authorization": f"Bearer {self.todoist_token}", "Content-Type": "application/json"}

        update_data = {}
        if "name" in params:
            update_data["name"] = params["name"]
        if "color" in params:
            update_data["color"] = params["color"]

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=update_data) as response:
                if response.status == 200:
                    label = await response.json()
                    return {"success": True, "label": label}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    async def _todoist_delete_label(self, label_id: str) -> Dict[str, Any]:
        """Delete a Todoist label"""
        import aiohttp

        url = f"https://api.todoist.com/rest/v2/labels/{label_id}"
        headers = {"Authorization": f"Bearer {self.todoist_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as response:
                if response.status == 204:
                    return {"success": True, "message": "Label deleted"}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    async def _todoist_update_section(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Update a Todoist section"""
        import aiohttp

        section_id = params["section_id"]
        url = f"https://api.todoist.com/rest/v2/sections/{section_id}"
        headers = {"Authorization": f"Bearer {self.todoist_token}", "Content-Type": "application/json"}

        update_data = {"name": params["name"]}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=update_data) as response:
                if response.status == 200:
                    section = await response.json()
                    return {"success": True, "section": section}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    async def _todoist_delete_section(self, section_id: str) -> Dict[str, Any]:
        """Delete a Todoist section"""
        import aiohttp

        url = f"https://api.todoist.com/rest/v2/sections/{section_id}"
        headers = {"Authorization": f"Bearer {self.todoist_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as response:
                if response.status == 204:
                    return {"success": True, "message": "Section deleted"}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    async def _todoist_update_comment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Update a Todoist comment"""
        import aiohttp

        comment_id = params["comment_id"]
        url = f"https://api.todoist.com/rest/v2/comments/{comment_id}"
        headers = {"Authorization": f"Bearer {self.todoist_token}", "Content-Type": "application/json"}

        update_data = {"content": params["content"]}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=update_data) as response:
                if response.status == 200:
                    comment = await response.json()
                    return {"success": True, "comment": comment}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    async def _todoist_delete_comment(self, comment_id: str) -> Dict[str, Any]:
        """Delete a Todoist comment"""
        import aiohttp

        url = f"https://api.todoist.com/rest/v2/comments/{comment_id}"
        headers = {"Authorization": f"Bearer {self.todoist_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as response:
                if response.status == 204:
                    return {"success": True, "message": "Comment deleted"}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Todoist API error: {response.status} - {error_text}"}

    # ===== ADDITIONAL GMAIL IMPLEMENTATIONS =====

    async def _gmail_delete_draft(self, draft_id: str) -> Dict[str, Any]:
        """Delete a Gmail draft"""
        import aiohttp

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_id}"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as response:
                if response.status == 204:
                    return {"success": True, "message": "Draft deleted"}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}

    async def _gmail_create_filter(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a Gmail filter"""
        import aiohttp

        url = "https://gmail.googleapis.com/gmail/v1/users/me/settings/filters"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}", "Content-Type": "application/json"}

        filter_data = {
            "criteria": params["criteria"],
            "action": params["action"]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=filter_data) as response:
                if response.status == 200:
                    filter_result = await response.json()
                    return {"success": True, "filter": filter_result}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}

    async def _gmail_list_filters(self) -> Dict[str, Any]:
        """List all Gmail filters"""
        import aiohttp

        url = "https://gmail.googleapis.com/gmail/v1/users/me/settings/filters"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    filters = data.get("filter", [])
                    return {"success": True, "filters": filters, "count": len(filters)}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}

    async def _gmail_delete_filter(self, filter_id: str) -> Dict[str, Any]:
        """Delete a Gmail filter"""
        import aiohttp

        url = f"https://gmail.googleapis.com/gmail/v1/users/me/settings/filters/{filter_id}"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        async with aiohttp.ClientSession() as session:
            async with session.delete(url, headers=headers) as response:
                if response.status == 204:
                    return {"success": True, "message": "Filter deleted"}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Gmail API error: {response.status} - {error_text}"}

    # ===== ADDITIONAL CALENDAR IMPLEMENTATIONS =====

    async def _calendar_add_attendee(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add an attendee to a calendar event"""
        import aiohttp

        calendar_id = params.get("calendar_id", "primary")
        event_id = params["event_id"]

        # First, get the current event
        get_url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(get_url, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return {"success": False, "error": f"Calendar API error: {response.status} - {error_text}"}

                event = await response.json()

            # Add the new attendee
            attendees = event.get("attendees", [])
            new_attendee = {
                "email": params["email"],
                "optional": params.get("optional", False)
            }
            attendees.append(new_attendee)
            event["attendees"] = attendees

            # Update the event
            headers["Content-Type"] = "application/json"
            async with session.put(get_url, headers=headers, json=event) as response:
                if response.status == 200:
                    updated_event = await response.json()
                    return {"success": True, "event": updated_event, "message": f"Added {params['email']} as attendee"}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Calendar API error: {response.status} - {error_text}"}

    async def _calendar_remove_attendee(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Remove an attendee from a calendar event"""
        import aiohttp

        calendar_id = params.get("calendar_id", "primary")
        event_id = params["event_id"]
        email_to_remove = params["email"]

        # First, get the current event
        get_url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}"
        headers = {"Authorization": f"Bearer {self._get_active_google_token()}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(get_url, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return {"success": False, "error": f"Calendar API error: {response.status} - {error_text}"}

                event = await response.json()

            # Remove the attendee
            attendees = event.get("attendees", [])
            original_count = len(attendees)
            attendees = [a for a in attendees if a.get("email") != email_to_remove]

            if len(attendees) == original_count:
                return {"success": False, "error": f"Attendee {email_to_remove} not found"}

            event["attendees"] = attendees

            # Update the event
            headers["Content-Type"] = "application/json"
            async with session.put(get_url, headers=headers, json=event) as response:
                if response.status == 200:
                    updated_event = await response.json()
                    return {"success": True, "event": updated_event, "message": f"Removed {email_to_remove} from attendees"}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Calendar API error: {response.status} - {error_text}"}

    # Google Maps tools implementation
    async def _google_maps_search_places(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search for places using Google Maps Places API"""
        import aiohttp

        query = params["query"]
        location = params.get("location", "")
        radius = params.get("radius", 5000)
        place_type = params.get("type", "")

        # Use Text Search API
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        request_params = {
            "query": query,
            "key": self.google_maps_api_key
        }

        if location:
            request_params["location"] = location
            request_params["radius"] = radius

        if place_type:
            request_params["type"] = place_type

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=request_params) as response:
                if response.status == 200:
                    data = await response.json()

                    if data.get("status") == "OK":
                        results = data.get("results", [])
                        places = []

                        for place in results[:10]:  # Limit to top 10
                            places.append({
                                "name": place.get("name"),
                                "address": place.get("formatted_address"),
                                "place_id": place.get("place_id"),
                                "rating": place.get("rating"),
                                "user_ratings_total": place.get("user_ratings_total"),
                                "types": place.get("types", []),
                                "location": place.get("geometry", {}).get("location"),
                                "open_now": place.get("opening_hours", {}).get("open_now")
                            })

                        return {
                            "success": True,
                            "count": len(places),
                            "places": places
                        }
                    else:
                        return {"success": False, "error": f"Maps API error: {data.get('status')} - {data.get('error_message', 'Unknown error')}"}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"HTTP error: {response.status} - {error_text}"}

    async def _google_maps_get_directions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get directions between two locations"""
        import aiohttp

        origin = params["origin"]
        destination = params["destination"]
        mode = params.get("mode", "driving")
        departure_time = params.get("departure_time")
        alternatives = params.get("alternatives", False)

        url = "https://maps.googleapis.com/maps/api/directions/json"
        request_params = {
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "alternatives": alternatives,
            "key": self.google_maps_api_key
        }

        if departure_time:
            if departure_time.lower() == "now":
                import time
                request_params["departure_time"] = int(time.time())
            else:
                # Parse ISO format timestamp
                from datetime import datetime
                try:
                    dt = datetime.fromisoformat(departure_time.replace('Z', '+00:00'))
                    request_params["departure_time"] = int(dt.timestamp())
                except:
                    pass

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=request_params) as response:
                if response.status == 200:
                    data = await response.json()

                    if data.get("status") == "OK":
                        routes = []

                        for route in data.get("routes", []):
                            leg = route["legs"][0]  # First leg

                            # Parse steps
                            steps = []
                            for step in leg.get("steps", []):
                                steps.append({
                                    "instruction": step.get("html_instructions", "").replace("<b>", "").replace("</b>", ""),
                                    "distance": step.get("distance", {}).get("text"),
                                    "duration": step.get("duration", {}).get("text"),
                                    "travel_mode": step.get("travel_mode")
                                })

                            routes.append({
                                "summary": route.get("summary"),
                                "distance": leg.get("distance", {}).get("text"),
                                "duration": leg.get("duration", {}).get("text"),
                                "start_address": leg.get("start_address"),
                                "end_address": leg.get("end_address"),
                                "steps": steps
                            })

                        return {
                            "success": True,
                            "count": len(routes),
                            "routes": routes
                        }
                    else:
                        return {"success": False, "error": f"Directions API error: {data.get('status')} - {data.get('error_message', 'Unknown error')}"}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"HTTP error: {response.status} - {error_text}"}

    async def _google_maps_get_place_details(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed information about a specific place"""
        import aiohttp

        place_id = params["place_id"]
        fields = params.get("fields", [
            "name", "formatted_address", "formatted_phone_number", "website",
            "opening_hours", "rating", "user_ratings_total", "reviews",
            "price_level", "business_status"
        ])

        url = "https://maps.googleapis.com/maps/api/place/details/json"
        request_params = {
            "place_id": place_id,
            "fields": ",".join(fields) if isinstance(fields, list) else fields,
            "key": self.google_maps_api_key
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=request_params) as response:
                if response.status == 200:
                    data = await response.json()

                    if data.get("status") == "OK":
                        result = data.get("result", {})

                        # Format reviews if present
                        reviews = []
                        for review in result.get("reviews", [])[:5]:  # Top 5 reviews
                            reviews.append({
                                "author": review.get("author_name"),
                                "rating": review.get("rating"),
                                "text": review.get("text"),
                                "time": review.get("relative_time_description")
                            })

                        return {
                            "success": True,
                            "place": {
                                "name": result.get("name"),
                                "address": result.get("formatted_address"),
                                "phone": result.get("formatted_phone_number"),
                                "website": result.get("website"),
                                "rating": result.get("rating"),
                                "user_ratings_total": result.get("user_ratings_total"),
                                "price_level": result.get("price_level"),
                                "business_status": result.get("business_status"),
                                "opening_hours": result.get("opening_hours", {}).get("weekday_text", []),
                                "is_open_now": result.get("opening_hours", {}).get("open_now"),
                                "reviews": reviews
                            }
                        }
                    else:
                        return {"success": False, "error": f"Place Details API error: {data.get('status')} - {data.get('error_message', 'Unknown error')}"}
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"HTTP error: {response.status} - {error_text}"}

    # Web search implementation
    async def _google_web_search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search the web using Google Custom Search API"""
        import aiohttp

        query = params["query"]
        num_results = params.get("num_results", 5)
        search_type = params.get("search_type", "web")
        site_restrict = params.get("site", "")
        date_restrict = params.get("date_restrict", "")

        url = "https://www.googleapis.com/customsearch/v1"
        request_params = {
            "key": self.google_custom_search_api_key,
            "cx": self.google_custom_search_engine_id,
            "q": query,
            "num": min(num_results, 10)  # API max is 10
        }

        if search_type == "image":
            request_params["searchType"] = "image"

        if site_restrict:
            request_params["siteSearch"] = site_restrict
            request_params["siteSearchFilter"] = "i"  # Include only this site

        if date_restrict:
            request_params["dateRestrict"] = date_restrict

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=request_params) as response:
                if response.status == 200:
                    data = await response.json()

                    items = data.get("items", [])
                    results = []

                    for item in items:
                        if search_type == "image":
                            results.append({
                                "title": item.get("title"),
                                "link": item.get("link"),
                                "thumbnail": item.get("image", {}).get("thumbnailLink"),
                                "context": item.get("image", {}).get("contextLink")
                            })
                        else:
                            results.append({
                                "title": item.get("title"),
                                "link": item.get("link"),
                                "snippet": item.get("snippet"),
                                "display_link": item.get("displayLink")
                            })

                    return {
                        "success": True,
                        "count": len(results),
                        "results": results,
                        "total_results": data.get("searchInformation", {}).get("totalResults"),
                        "search_time": data.get("searchInformation", {}).get("searchTime")
                    }
                else:
                    error_text = await response.text()
                    return {"success": False, "error": f"Custom Search API error: {response.status} - {error_text}"}


# Global MCP client instance
mcp_client = MCPClient()
