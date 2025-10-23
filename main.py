"""
WhatsApp + Claude Integration
Receives WhatsApp messages via Twilio webhook and responds using Claude API
"""

import os
from fastapi import FastAPI, Form, Request
from fastapi.responses import Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import anthropic
from typing import Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WhatsApp Claude Bot")

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


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "WhatsApp Claude Bot",
        "version": "1.0.0"
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

        # Get Claude's response
        logger.info("Calling Claude API...")
        response = claude_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=1024,
            system="You are a helpful assistant responding to WhatsApp messages. Keep responses concise and friendly.",
            messages=conversation_history[user_id]
        )

        assistant_message = response.content[0].text
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
