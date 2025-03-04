from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi import Request
from pydantic import BaseModel
import json
import uvicorn
import time
import uuid
import logging
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from bson import ObjectId
from typing import List, Dict
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# MongoDB Connection
class MongoChatManager:
    def __init__(self, connection_string=None):
        # Use environment variable or passed connection string
        if not connection_string:
            connection_string = os.getenv('MONGODB_URI')
        
        if not connection_string:
            raise ValueError("MongoDB connection string is required")
        
        try:
            # Create a new client and connect to the server
            self.client = MongoClient(connection_string, server_api=ServerApi('1'))
            
            # Verify connection
            self.client.admin.command('ping')
            logger.info("Successfully connected to MongoDB Atlas!")
            
            # Select database
            self.db = self.client['chat_application']
            self.chats_collection = self.db['chats']
            self.messages_collection = self.db['messages']
            
            # Create indexes for better performance
            self.create_indexes()
        
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    def create_indexes(self):
        # Create indexes to improve query performance
        self.chats_collection.create_index([('participants', 1)])
        self.messages_collection.create_index([('chat_id', 1), ('timestamp', 1)])

    def create_chat(self, initiator: str, participant: str) -> str:
        """Create a new chat between two users."""
        # Check if chat already exists
        existing_chat = self.chats_collection.find_one({
            'participants': {'$all': [initiator, participant]}
        })
        
        if existing_chat:
            return str(existing_chat['_id'])
        
        chat_document = {
            'participants': [initiator, participant],
            'created_at': time.time(),
            'last_message_at': None
        }
        result = self.chats_collection.insert_one(chat_document)
        return str(result.inserted_id)

    def add_message_to_chat(self, chat_id: str, sender: str, message: str) -> Dict:
        """Add a message to a specific chat."""
        message_document = {
            'chat_id': chat_id,
            'sender': sender,
            'message': message,
            'timestamp': time.time()
        }
        
        # Insert message
        self.messages_collection.insert_one(message_document)
        
        # Update last message timestamp in chat
        self.chats_collection.update_one(
            {'_id': ObjectId(chat_id)},
            {'$set': {'last_message_at': time.time()}}
        )
        
        return message_document

    def get_user_chats(self, username: str) -> List[Dict]:
        """Retrieve all chats for a user."""
        # Find chats where the user is a participant
        user_chats = self.chats_collection.find({
            'participants': username
        })
        
        chat_list = []
        for chat in user_chats:
            # Find the other participant
            participants = list(chat['participants'])
            participants.remove(username)
            other_participant = participants[0] if participants else 'Unknown'
            
            # Find the last message
            last_message = self.messages_collection.find_one(
                {'chat_id': str(chat['_id'])}, 
                sort=[('timestamp', -1)]
            )
            
            chat_list.append({
                'chat_id': str(chat['_id']),
                'participant': other_participant,
                'last_message': last_message['message'] if last_message else '',
                'timestamp': chat.get('last_message_at', chat['created_at'])
            })
        
        return chat_list

    def get_chat_messages(self, chat_id: str) -> List[Dict]:
        """Get messages for a specific chat."""
        messages = list(self.messages_collection.find(
            {'chat_id': chat_id}, 
            sort=[('timestamp', 1)]
        ))
        
        # Convert ObjectId to string
        for msg in messages:
            msg['_id'] = str(msg['_id'])
        
        return messages

# Create a global chat manager
chat_manager = MongoChatManager()

# Pydantic models for request validation
class CreateChatRequest(BaseModel):
    initiator: str
    participant: str

class SendMessageRequest(BaseModel):
    sender: str
    chat_id: str
    message: str

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Add more comprehensive CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global storage for active WebSocket connections
active_connections = {}

@app.get("/")
async def read_root(request: Request):
    """Serve the main HTML page."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/create-chat")
async def create_chat(request: CreateChatRequest):
    """Endpoint to create a new chat."""
    try:
        chat_id = chat_manager.create_chat(request.initiator, request.participant)
        return {"chat_id": chat_id}
    except Exception as e:
        logger.error(f"Error creating chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user-chats/{username}")
async def get_user_chats(username: str):
    """Get all chats for a user."""
    return chat_manager.get_user_chats(username)

@app.get("/chat-messages/{chat_id}")
async def get_chat_messages(chat_id: str):
    """Get messages for a specific chat."""
    return chat_manager.get_chat_messages(chat_id)

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await websocket.accept()
    
    # Store the websocket connection
    active_connections[username] = websocket
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            # Handle different types of WebSocket messages
            if message_data.get('type') == 'create_chat':
                # Create a new chat
                initiator = message_data.get('initiator')
                participant = message_data.get('participant')
                chat_id = chat_manager.create_chat(initiator, participant)
                
                await websocket.send_text(json.dumps({
                    'type': 'chat_created',
                    'chat_id': chat_id,
                    'participant': participant
                }))
            
            elif message_data.get('type') == 'send_message':
                # Send a message in a specific chat
                chat_id = message_data.get('chat_id')
                sender = message_data.get('sender')
                message = message_data.get('message')
                
                try:
                    # Add message to chat
                    message_entry = chat_manager.add_message_to_chat(chat_id, sender, message)
                    
                    # Broadcast to all participants in the chat
                    chat = chat_manager.chats_collection.find_one({'_id': ObjectId(chat_id)})
                    for participant in chat.get('participants', []):
                        if participant in active_connections:
                            await active_connections[participant].send_text(json.dumps({
                                'type': 'new_message',
                                'chat_id': chat_id,
                                'sender': sender,
                                'message': message
                            }))
                
                except Exception as e:
                    logger.error(f"Error sending message: {e}")
                    await websocket.send_text(json.dumps({
                        'type': 'error',
                        'message': str(e)
                    }))
    
    except WebSocketDisconnect:
        logger.info(f"{username} disconnected")
    finally:
        # Clean up connection
        if username in active_connections:
            del active_connections[username]

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)