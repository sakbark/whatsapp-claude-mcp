"""
WhatsApp + Claude + MCP Integration
Receives WhatsApp messages via Twilio webhook and responds using Claude API with MCP tools
"""

import os
from fastapi import FastAPI, Form, Request
from fastapi.responses import Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import anthropic
from typing import Optional
import logging
import asyncio

# Import MCP client
from mcp_client import mcp_client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WhatsApp Claude MCP Bot")

# Initialize clients
twilio_client = Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

claude_client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

# Store conversation history (in production, use a database)
conversation_history = {}


@app.on_event("startup")
async def startup_event():
    """Initialize MCP client on startup"""
    logger.info("Starting up WhatsApp Claude MCP Bot...")
    await mcp_client.initialize()
    logger.info("MCP client initialized successfully")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "WhatsApp Claude MCP Bot",
        "version": "2.0.0",
        "mcp_enabled": len(mcp_client.available_tools) > 0,
        "available_tools": len(mcp_client.available_tools)
    }


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    Body: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    MessageSid: str = Form(...),
    NumMedia: Optional[str] = Form(None)
):
    """
    Webhook endpoint for incoming WhatsApp messages from Twilio

    Twilio sends form-encoded data with:
    - Body: Message text
    - From: Sender's WhatsApp number (format: whatsapp:+1234567890)
    - To: Your WhatsApp number
    - MessageSid: Unique message ID
    """

    logger.info(f"Received message from {From}: {Body}")

    try:
        # Get or create conversation history for this user
        user_id = From
        if user_id not in conversation_history:
            conversation_history[user_id] = []

        # Add user message to history
        conversation_history[user_id].append({
            "role": "user",
            "content": Body
        })

        # Keep only last 10 messages to avoid token limits
        if len(conversation_history[user_id]) > 10:
            conversation_history[user_id] = conversation_history[user_id][-10:]

        # Get Claude's response with MCP tools
        logger.info("Calling Claude API with MCP tools...")

        system_prompt = """You are a personal AI assistant communicating via WhatsApp.

The person messaging you is Saad, and you have access to his tools:
- List his tasks with todoist_get_tasks
- Create new tasks with todoist_create_task
- Complete tasks with todoist_complete_task

About Saad:
- Developer working on AI and automation projects
- Located in UK
- Prefers concise, direct responses

Keep responses friendly but brief since this is WhatsApp.
When showing tasks, format them clearly and concisely.
Always confirm after creating or completing tasks.

When Saad asks about "my tasks" or "my todo list", use the tools to access HIS Todoist account."""

        assistant_message = await mcp_client.chat_with_tools(
            messages=conversation_history[user_id],
            system_prompt=system_prompt,
            max_turns=5
        )

        logger.info(f"Claude response: {assistant_message}")

        # Add assistant response to history
        conversation_history[user_id].append({
            "role": "assistant",
            "content": assistant_message
        })

        # Create Twilio response
        twiml_response = MessagingResponse()
        twiml_response.message(assistant_message)

        logger.info("Sending response back to WhatsApp")

        return Response(
            content=str(twiml_response),
            media_type="application/xml"
        )

    except Exception as e:
        logger.error(f"Error processing message: {str(e)}", exc_info=True)

        # Send error message back to user
        twiml_response = MessagingResponse()
        twiml_response.message("Sorry, I encountered an error processing your message. Please try again.")

        return Response(
            content=str(twiml_response),
            media_type="application/xml"
        )


@app.post("/send")
async def send_message(request: Request):
    """
    API endpoint to manually send WhatsApp messages

    POST body:
    {
        "to": "whatsapp:+1234567890",
        "message": "Hello from the API!"
    }
    """
    try:
        data = await request.json()
        to_number = data.get("to")
        message_text = data.get("message")

        if not to_number or not message_text:
            return {
                "success": False,
                "error": "Missing 'to' or 'message' in request body"
            }

        # Send via Twilio
        message = twilio_client.messages.create(
            from_=f"whatsapp:{os.getenv('TWILIO_WHATSAPP_NUMBER')}",
            to=to_number,
            body=message_text
        )

        logger.info(f"Sent message {message.sid} to {to_number}")

        return {
            "success": True,
            "message_sid": message.sid,
            "to": to_number
        }

    except Exception as e:
        logger.error(f"Error sending message: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


@app.get("/conversations")
async def get_conversations():
    """
    Get all active conversations (for future dashboard)
    """
    conversations = []
    for user_id, history in conversation_history.items():
        conversations.append({
            "user_id": user_id,
            "message_count": len(history),
            "last_message": history[-1] if history else None
        })

    return {
        "conversations": conversations,
        "total": len(conversations)
    }


# SMS receiver for getting verification codes
sms_messages = []

@app.post("/webhook/sms")
async def sms_webhook(
    Body: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    MessageSid: str = Form(...)
):
    """
    Webhook for incoming SMS messages
    Stores them so you can retrieve verification codes
    """
    logger.info(f"Received SMS from {From}: {Body}")

    sms_messages.append({
        "from": From,
        "to": To,
        "body": Body,
        "sid": MessageSid
    })

    # Keep only last 50 messages
    if len(sms_messages) > 50:
        sms_messages.pop(0)

    return {"status": "received"}


@app.get("/sms/latest")
async def get_latest_sms():
    """
    Get all received SMS messages
    Use this to retrieve your verification codes
    """
    return {
        "messages": sms_messages,
        "count": len(sms_messages)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
