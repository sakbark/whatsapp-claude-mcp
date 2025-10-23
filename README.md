# WhatsApp + Claude + MCP Integration

**Claude Code via WhatsApp** - A powerful WhatsApp bot with full MCP server integration, giving Claude access to Todoist, Gmail, Google Calendar, Airtable, and more.

## 🎯 Vision

Create a WhatsApp interface to Claude with all the capabilities of Claude Code:
- Manage tasks in Todoist
- Read and send emails via Gmail
- Create calendar events
- Access Airtable databases
- Search and manipulate files
- And much more through MCP servers

## 🏗️ Architecture

```
WhatsApp Message
    ↓
Twilio Webhook
    ↓
Cloud Run Service
    ↓
MCP Client (connects to multiple MCP servers)
    ↓
Claude API (with tool calling)
    ↓
Tool Execution Loop
    ↓
Response back to WhatsApp
```

## 📦 Current Status

**Phase 1: Basic WhatsApp Integration** ✅
- [x] FastAPI webhook server
- [x] Twilio WhatsApp integration
- [x] Basic Claude API integration
- [x] Cloud Run deployment
- [x] Conversation memory

**Phase 2: MCP Integration** 🚧 (In Progress)
- [ ] MCP client integration
- [ ] Tool execution loop
- [ ] Multi-turn conversation handling
- [ ] Connect to Todoist MCP
- [ ] Connect to Gmail MCP
- [ ] Connect to Google Calendar MCP
- [ ] Connect to Airtable MCP
- [ ] Connect to other MCP servers

**Phase 3: Advanced Features** 📋 (Planned)
- [ ] Multi-user dashboard
- [ ] User authentication
- [ ] Conversation state persistence (database)
- [ ] Production WhatsApp number
- [ ] Media message support
- [ ] Analytics and logging

## 🔧 Tech Stack

- **Backend:** Python, FastAPI
- **AI:** Anthropic Claude API
- **Messaging:** Twilio WhatsApp API
- **MCP:** Model Context Protocol clients
- **Deployment:** Google Cloud Run
- **Secrets:** Google Secret Manager

## 🚀 Quick Start

### Prerequisites

1. Twilio Account with WhatsApp enabled
2. Anthropic API Key
3. Google Cloud Project
4. MCP server configurations (stored in GSM)

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your credentials

# Run locally
python main.py

# Test with ngrok
ngrok http 8080
```

### Deploy to Cloud Run

```bash
# Set your project
export PROJECT_ID=new-fps-gpt
export REGION=us-central1

# Deploy
gcloud run deploy whatsapp-claude-bot \
  --source . \
  --region $REGION \
  --platform managed \
  --allow-unauthenticated \
  --project $PROJECT_ID
```

## 📝 Environment Variables

All secrets are stored in Google Secret Manager:

| Variable | Description |
|----------|-------------|
| `TWILIO_ACCOUNT_SID` | Your Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Your Twilio Auth Token |
| `TWILIO_WHATSAPP_NUMBER` | Your Twilio WhatsApp number |
| `ANTHROPIC_API_KEY` | Your Anthropic API key |

## 🔐 Security

- All credentials stored in Google Secret Manager
- MCP server authentication tokens managed securely
- WhatsApp webhook validates Twilio signatures
- User authentication required for sensitive operations

## 📚 MCP Servers Integrated

- **Todoist:** Task management
- **Gmail:** Email reading and sending
- **Google Calendar:** Event management
- **Airtable:** Database operations
- **Google Drive:** File operations
- **And more...**

## 🎯 Use Cases

1. **Task Management:** "Add a task to buy groceries tomorrow"
2. **Email Management:** "Show me unread emails from today"
3. **Calendar:** "What's on my calendar this week?"
4. **Data Access:** "Get records from my Airtable base"
5. **File Search:** "Find my contract document"

## 🤝 Contributing

This is a personal project, but contributions are welcome!

## 📄 License

MIT

## 🙏 Acknowledgments

- Anthropic for Claude API
- Twilio for WhatsApp integration
- MCP protocol and community
