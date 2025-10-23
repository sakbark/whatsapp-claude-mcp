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
import uuid
from datetime import datetime

# Import MCP client
from mcp_client import mcp_client

# Import error handling utilities
from error_handler import (
    ErrorContext,
    retry_with_backoff,
    format_error_for_user,
    validate_image_size,
    APIError,
    TranscriptionError,
    ImageProcessingError,
    circuit_breakers,
)

# Configure structured logging with more detail
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="WhatsApp Claude MCP Bot")

# Clients will be initialized during startup from GSM
twilio_client = None
claude_client = None
openai_client = None
twilio_whatsapp_number = None  # Twilio WhatsApp number from GSM


@retry_with_backoff(max_retries=2, initial_delay=0.5, exceptions=(Exception,))
async def _get_secret(secret_name: str, project_id: str = "new-fps-gpt") -> Optional[str]:
    """
    Fetch a secret from Google Secret Manager with retry logic
    Returns None if secret doesn't exist or can't be accessed after retries
    """
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"

        response = client.access_secret_version(request={"name": name})
        secret_value = response.payload.data.decode("UTF-8")

        logger.info(f"✅ Successfully retrieved secret: {secret_name}")
        return secret_value

    except Exception as e:
        logger.warning(f"⚠️  Failed to retrieve secret {secret_name}: {str(e)}")
        raise  # Re-raise for retry decorator to catch

# Store conversation history (in production, use a database)
conversation_history = {}

# Store active account per user (work or personal)
active_accounts = {}  # {user_id: "work" or "personal"}

# Error tracking for monitoring
error_stats = {
    "total_errors": 0,
    "last_error": None,
    "error_by_type": {},
    "circuit_breaker_trips": 0
}


@app.on_event("startup")
async def startup_event():
    """Initialize all clients on startup"""
    global openai_client, twilio_client, claude_client, twilio_whatsapp_number

    logger.info("Starting up WhatsApp Claude MCP Bot...")

    # Initialize MCP client
    await mcp_client.initialize()
    logger.info("✅ MCP client initialized successfully")

    # Load Twilio credentials from GSM
    try:
        twilio_sid = await _get_secret("twilio-account-sid")
        twilio_token = await _get_secret("twilio-auth-token")

        if twilio_sid and twilio_token:
            twilio_client = Client(twilio_sid, twilio_token)
            logger.info("✅ Twilio client initialized")
    except Exception as e:
        logger.error(f"❌ Failed to load Twilio credentials: {str(e)}")

    try:
        whatsapp_num = await _get_secret("twilio-whatsapp-number")
        if whatsapp_num:
            twilio_whatsapp_number = whatsapp_num
            logger.info(f"✅ Twilio WhatsApp number loaded: {twilio_whatsapp_number}")
    except Exception as e:
        logger.warning(f"⚠️  Twilio WhatsApp number not found in GSM: {str(e)}")

    # Load Anthropic API key from GSM
    try:
        anthropic_key = await _get_secret("anthropic-api-key")
        if anthropic_key:
            claude_client = anthropic.Anthropic(api_key=anthropic_key)
            logger.info("✅ Claude client initialized")
    except Exception as e:
        logger.error(f"❌ Failed to load Anthropic API key: {str(e)}")

    # Load OpenAI API key from GSM
    try:
        openai_api_key = await _get_secret("openai-api-key")
        if openai_api_key:
            from openai import AsyncOpenAI
            openai_client = AsyncOpenAI(api_key=openai_api_key)
            logger.info("✅ OpenAI client initialized for audio transcription")
    except Exception as e:
        logger.warning(f"⚠️  OpenAI API key not found in GSM: {str(e)}")


@app.get("/")
async def root():
    """Basic health check endpoint"""
    return {
        "status": "healthy",
        "service": "WhatsApp Claude MCP Bot",
        "version": "2.1.0",
        "mcp_enabled": len(mcp_client.available_tools) > 0,
        "available_tools": len(mcp_client.available_tools),
        "openai_enabled": openai_client is not None,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/health")
async def health_check():
    """Comprehensive health check with circuit breaker status"""
    circuit_status = {}
    for name, breaker in circuit_breakers.items():
        circuit_status[name] = {
            "state": breaker.state,
            "failure_count": breaker.failure_count,
            "last_failure": breaker.last_failure_time.isoformat() if breaker.last_failure_time else None
        }

    return {
        "status": "healthy",
        "service": "WhatsApp Claude MCP Bot",
        "version": "2.1.0",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "mcp_client": {
                "enabled": True,
                "tools_count": len(mcp_client.available_tools),
                "status": "operational"
            },
            "openai_whisper": {
                "enabled": openai_client is not None,
                "status": "operational" if openai_client else "disabled"
            },
            "circuit_breakers": circuit_status
        },
        "error_stats": {
            "total_errors": error_stats["total_errors"],
            "last_error_time": error_stats["last_error"]["timestamp"] if error_stats["last_error"] else None,
            "error_types": error_stats["error_by_type"],
            "circuit_breaker_trips": error_stats["circuit_breaker_trips"]
        },
        "conversations": {
            "active": len(conversation_history),
            "total_messages": sum(len(h) for h in conversation_history.values())
        }
    }


@retry_with_backoff(max_retries=2, exceptions=(APIError,), circuit_breaker_name="whisper")
async def process_audio_transcription(media_bytes: bytes, media_type: str) -> str:
    """Process audio transcription with error handling and retry logic"""
    if not openai_client:
        raise TranscriptionError(
            "OpenAI client not initialized",
            "Audio transcription is not available. Please send text instead."
        )

    async with ErrorContext("transcribing audio", log_errors=True) as ctx:
        import tempfile

        # Save audio temporarily for Whisper API
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_audio:
            temp_audio.write(media_bytes)
            temp_audio_path = temp_audio.name

        try:
            # Transcribe using OpenAI Whisper
            with open(temp_audio_path, "rb") as audio_file:
                transcript = await openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text"
                )

            transcribed_text = transcript.strip()
            logger.info(f"✅ Transcribed audio ({len(media_bytes)} bytes): {transcribed_text[:100]}...")
            ctx.set_result(transcribed_text)
            return transcribed_text

        finally:
            # Always clean up temp file
            if os.path.exists(temp_audio_path):
                os.remove(temp_audio_path)


@retry_with_backoff(max_retries=1, exceptions=(ImageProcessingError,))
async def process_image(media_bytes: bytes, media_type: str) -> dict:
    """Process image with compression and validation"""
    async with ErrorContext("processing image", log_errors=True) as ctx:
        import base64
        from PIL import Image
        import io

        # Normalize media type
        media_type = media_type.lower()
        supported_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]

        if media_type not in supported_types:
            if "jpg" in media_type or "jpeg" in media_type:
                media_type = "image/jpeg"
            elif "png" in media_type:
                media_type = "image/png"
            elif "gif" in media_type:
                media_type = "image/gif"
            elif "webp" in media_type:
                media_type = "image/webp"
            else:
                logger.warning(f"Unsupported media type: {media_type}, defaulting to image/jpeg")
                media_type = "image/jpeg"

        # Validate and compress if needed
        image_size_mb = len(media_bytes) / (1024 * 1024)
        logger.info(f"📸 Image size: {image_size_mb:.2f} MB, type: {media_type}")

        if image_size_mb > 10.0:
            raise ImageProcessingError(
                f"Image too large: {image_size_mb:.2f}MB",
                f"Image is too large ({image_size_mb:.1f}MB). Please send an image smaller than 10MB."
            )

        # Compress if larger than 4.5MB
        if image_size_mb > 4.5:
            logger.info(f"🗜️  Compressing image from {image_size_mb:.2f} MB...")
            try:
                img = Image.open(io.BytesIO(media_bytes))
                img.thumbnail((1920, 1920), Image.Resampling.LANCZOS)

                output = io.BytesIO()
                img.save(output, format='JPEG', quality=85, optimize=True)
                media_bytes = output.getvalue()
                media_type = "image/jpeg"

                new_size_mb = len(media_bytes) / (1024 * 1024)
                logger.info(f"✅ Compressed: {image_size_mb:.2f} MB → {new_size_mb:.2f} MB")
            except Exception as e:
                logger.warning(f"⚠️  Compression failed: {str(e)}, using original image")

        media_content = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(media_bytes).decode("utf-8")
            }
        }

        logger.info(f"✅ Image ready for Claude (type: {media_type})")
        ctx.set_result(media_content)
        return media_content


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    Body: str = Form(""),
    From: str = Form(...),
    To: str = Form(...),
    MessageSid: str = Form(...),
    NumMedia: Optional[str] = Form(None),
    MediaUrl0: Optional[str] = Form(None),
    MediaContentType0: Optional[str] = Form(None)
):
    """
    Webhook endpoint for incoming WhatsApp messages from Twilio
    Enhanced with comprehensive error handling and logging
    """
    # Generate request ID for tracking
    request_id = str(uuid.uuid4())[:8]
    start_time = datetime.now()

    logger.info(f"[{request_id}] 📨 Received message from {From}: '{Body[:100]}' (NumMedia: {NumMedia})")

    try:
        # Get or create conversation history for this user
        user_id = From
        if user_id not in conversation_history:
            conversation_history[user_id] = []

        # Check for account switching commands
        if Body:
            body_lower = Body.lower().strip()
            if "use work account" in body_lower or "switch to work" in body_lower:
                active_accounts[user_id] = "work"
                logger.info(f"✅ Switched {user_id} to work account")

                twiml_response = MessagingResponse()
                twiml_response.message("✅ Switched to work account. All Google tools will now use your work account.")
                return Response(content=str(twiml_response), media_type="application/xml")

            elif "use personal account" in body_lower or "switch to personal" in body_lower or "use home account" in body_lower:
                active_accounts[user_id] = "personal"
                logger.info(f"✅ Switched {user_id} to personal account")

                twiml_response = MessagingResponse()
                twiml_response.message("✅ Switched to personal account. All Google tools will now use your personal account.")
                return Response(content=str(twiml_response), media_type="application/xml")

            elif "which account" in body_lower or "what account" in body_lower or "current account" in body_lower:
                current_account = active_accounts.get(user_id, "personal")  # Default to personal
                twiml_response = MessagingResponse()
                twiml_response.message(f"You're currently using your **{current_account}** account.\n\nSay 'use work account' or 'use personal account' to switch.")
                return Response(content=str(twiml_response), media_type="application/xml")

        # Process media if present
        media_content = None
        if NumMedia and int(NumMedia) > 0 and MediaUrl0:
            logger.info(f"[{request_id}] 📎 Processing media: {MediaContentType0} from {MediaUrl0}")

            try:
                import httpx

                # Download media from Twilio with timeout
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                    async with ErrorContext(f"downloading media from Twilio", log_errors=True) as ctx:
                        media_response = await client.get(MediaUrl0)
                        media_bytes = media_response.content
                        logger.info(f"[{request_id}] ✅ Downloaded {len(media_bytes)} bytes")

                # Handle images
                if MediaContentType0 and "image" in MediaContentType0:
                    try:
                        media_content = await process_image(media_bytes, MediaContentType0)
                        logger.info(f"[{request_id}] ✅ Image processed successfully")
                    except (ImageProcessingError, Exception) as e:
                        logger.error(f"[{request_id}] ❌ Image processing failed: {str(e)}")
                        error_msg = format_error_for_user(e, "processing image")
                        Body = f"{Body}\n\n{error_msg}" if Body else error_msg
                        media_content = None

                # Handle audio
                elif MediaContentType0 and "audio" in MediaContentType0:
                    try:
                        transcribed_text = await process_audio_transcription(media_bytes, MediaContentType0)
                        Body = f"[Voice message]: {transcribed_text}"
                        logger.info(f"[{request_id}] ✅ Audio transcribed successfully")
                    except (TranscriptionError, Exception) as e:
                        logger.error(f"[{request_id}] ❌ Audio transcription failed: {str(e)}")
                        error_msg = format_error_for_user(e, "transcribing audio")
                        Body = f"[Voice message]: {error_msg}"

            except Exception as e:
                logger.error(f"[{request_id}] ❌ Media download failed: {str(e)}")
                error_msg = format_error_for_user(e, "downloading media")
                Body = f"{Body}\n\n{error_msg}" if Body else error_msg

        # Build message content with media if present
        if media_content and media_content["type"] == "image":
            # For images, create a multi-part message
            conversation_history[user_id].append({
                "role": "user",
                "content": [
                    {"type": "text", "text": Body if Body else "What's in this image?"},
                    media_content
                ]
            })
        else:
            # Text only
            conversation_history[user_id].append({
                "role": "user",
                "content": Body if Body else "[Media received]"
            })

        # Keep only last 10 messages to avoid token limits
        if len(conversation_history[user_id]) > 10:
            conversation_history[user_id] = conversation_history[user_id][-10:]

        # Get Claude's response with MCP tools
        logger.info(f"[{request_id}] 🤖 Calling Claude API with MCP tools...")
        active_account = active_accounts.get(user_id, "personal")

        system_prompt = f"""You are a personal AI assistant communicating via WhatsApp.

The person messaging you from {From} is Saad (verified by phone number +447933993951).
You have access to 58 powerful tools to help manage his digital life:

**Todoist (21 tools - Full CRUD):**
- Tasks: get, create, update, delete, complete
- Projects: list, create, update, delete
- Labels: list, create, update, delete
- Sections: list, create
- Comments: add, list

**Gmail (23 tools - Full email management):**
- Search, send (basic & advanced with CC/BCC/HTML), read, reply, delete
- Drafts: create, list, send, delete
- Labels: list, create, update, delete
- Filters: create, list, delete
- Attachments: download
- Threads: retrieve full conversations

**Google Calendar (10 tools):**
- Events: list, create (basic & advanced), update, delete, search
- Advanced: Google Meet links, recurring events, all-day events
- Attendees: add, remove
- Free/busy: check availability
- Multiple calendars support

**Google Maps (3 tools):**
- Search places (restaurants, businesses, landmarks)
- Get directions (driving, walking, transit, bicycling)
- Place details (hours, reviews, phone, website)

**Web Search (1 tool):**
- Google web search with filters (site-specific, date range, image search)

About Saad:
- Developer working on AI and automation projects
- Located in UK (Europe/London timezone)
- Prefers concise, direct responses

Keep responses friendly but brief since this is WhatsApp.
When showing tasks/emails/events, format them clearly and concisely.
Always confirm after creating or completing items.

**CRITICAL: Error Handling**
- If any tool returns an error (success: false), you MUST tell Saad about the error immediately
- Never go silent or hallucinate data when tools fail
- Show the actual error message so he can troubleshoot
- Example: "I got an error accessing your calendar: [error details]"
- NEVER make up fake data if the real data is unavailable

**Response Timing:**
- If you need to use multiple tools or the request is complex, start your response with a quick acknowledgment
- Example: "Let me check your calendar... " or "Searching your emails now..." or "Looking up directions..."
- This lets Saad know you're working on it"""

        try:
            async with ErrorContext(f"calling Claude API for user {user_id}", log_errors=True) as ctx:
                assistant_message = await mcp_client.chat_with_tools(
                    messages=conversation_history[user_id],
                    system_prompt=system_prompt,
                    max_turns=5,
                    active_account=active_account
                )
                ctx.set_result(assistant_message)

            logger.info(f"[{request_id}] ✅ Claude response received ({len(assistant_message)} chars)")

        except Exception as e:
            logger.error(f"[{request_id}] ❌ Claude API call failed: {str(e)}")
            error_stats["total_errors"] += 1
            error_type = type(e).__name__
            error_stats["error_by_type"][error_type] = error_stats["error_by_type"].get(error_type, 0) + 1
            error_stats["last_error"] = {
                "type": error_type,
                "message": str(e),
                "timestamp": datetime.now().isoformat(),
                "request_id": request_id
            }

            assistant_message = format_error_for_user(e, "getting AI response")

        # Add assistant response to history
        conversation_history[user_id].append({
            "role": "assistant",
            "content": assistant_message
        })

        # Create Twilio response
        twiml_response = MessagingResponse()
        twiml_response.message(assistant_message)

        # Log successful request
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"[{request_id}] ✅ Request completed successfully in {duration:.2f}s "
            f"(msg_len={len(assistant_message)}, media={bool(media_content)})"
        )

        return Response(
            content=str(twiml_response),
            media_type="application/xml"
        )

    except Exception as e:
        # Track error
        duration = (datetime.now() - start_time).total_seconds()
        error_type = type(e).__name__

        error_stats["total_errors"] += 1
        error_stats["error_by_type"][error_type] = error_stats["error_by_type"].get(error_type, 0) + 1
        error_stats["last_error"] = {
            "type": error_type,
            "message": str(e),
            "timestamp": datetime.now().isoformat(),
            "request_id": request_id,
            "user_id": From,
            "duration": duration
        }

        # Comprehensive error logging
        logger.error(
            f"[{request_id}] ❌ FATAL ERROR processing message after {duration:.2f}s\n"
            f"Error Type: {error_type}\n"
            f"Error Message: {str(e)}\n"
            f"User: {From}\n"
            f"Message: {Body[:200] if Body else '[No text]'}\n"
            f"Media: {MediaContentType0 if MediaContentType0 else 'None'}\n"
            f"Full Traceback:",
            exc_info=True
        )

        # Send user-friendly error message
        user_error_msg = format_error_for_user(e, "processing your message")
        twiml_response = MessagingResponse()
        twiml_response.message(user_error_msg)

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

        if not twilio_client:
            return {
                "success": False,
                "error": "Twilio client not initialized"
            }

        if not twilio_whatsapp_number:
            return {
                "success": False,
                "error": "Twilio WhatsApp number not configured"
            }

        # Send via Twilio
        message = twilio_client.messages.create(
            from_=f"whatsapp:{twilio_whatsapp_number}",
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
