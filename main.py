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
from typing import List, Dict, Union
import os
from dotenv import load_dotenv
import bcrypt  # For password hashing
import secrets  # For generating tokens

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# MongoDB Connection
class MongoUserManager:
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
            self.users_collection = self.db['users']
            self.tokens_collection = self.db['tokens']
            self.chats_collection = self.db['chats']
            self.messages_collection = self.db['messages']
            
            # Create indexes
            self.create_indexes()
        
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    def create_indexes(self):
        # Create unique index for username
        self.users_collection.create_index('username', unique=True)
        # Create index for tokens with expiration
        self.tokens_collection.create_index('token', unique=True)
        self.tokens_collection.create_index('expires_at', expireAfterSeconds=0)
        
        # Create indexes for chats and messages
        self.chats_collection.create_index([('participants', 1)])
        self.messages_collection.create_index([('chat_id', 1), ('timestamp', 1)])

    def register_user(self, username: str, password: str) -> bool:
        """Register a new user."""
        # Check if username already exists
        existing_user = self.users_collection.find_one({'username': username})
        if existing_user:
            return False
        
        # Hash the password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        # Insert user
        user_document = {
            'username': username,
            'password': hashed_password,
            'created_at': time.time()
        }
        self.users_collection.insert_one(user_document)
        return True

    def validate_user(self, username: str, password: str) -> bool:
        """Validate user credentials."""
        user = self.users_collection.find_one({'username': username})
        if not user:
            return False
        
        # Check password
        return bcrypt.checkpw(password.encode('utf-8'), user['password'])

    def generate_token(self, username: str) -> str:
        """Generate a login token for a user."""
        # Delete any existing tokens for this user
        self.tokens_collection.delete_many({'username': username})
        
        # Generate a new token
        token = secrets.token_urlsafe(32)
        token_document = {
            'username': username,
            'token': token,
            'created_at': time.time(),
            'expires_at': time.time() + (24 * 60 * 60)  # Token valid for 24 hours
        }
        self.tokens_collection.insert_one(token_document)
        return token

    def validate_token(self, token: str) -> str:
        """Validate a login token and return username."""
        token_doc = self.tokens_collection.find_one({'token': token})
        if not token_doc:
            return None
        return token_doc['username']

    def create_chat(self, initiator: str, participants: Union[str, List[str]], is_group: bool = False) -> str:
        """Create a new chat, support both single and group chats."""
        # Ensure participants is a list
        if isinstance(participants, str):
            participants = [initiator, participants]
        elif initiator not in participants:
            participants.append(initiator)

        # Check if chat already exists for non-group chats
        if not is_group:
            existing_chat = self.chats_collection.find_one({
                'participants': {'$all': participants},
                'is_group': False
            })
            if existing_chat:
                return str(existing_chat['_id'])

        chat_document = {
            'participants': participants,
            'created_at': time.time(),
            'last_message_at': None,
            'is_group': is_group,
            'chat_name': participants[0] if is_group else None  # Optional group name
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
            # Determine other participants or chat name
            if chat.get('is_group', False):
                chat_name = chat.get('chat_name', 'Group Chat')
                other_participant = chat_name
            else:
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
                'is_group': chat.get('is_group', False),
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

# Global user and chat manager
user_manager = MongoUserManager()

# Pydantic models for request validation
class RegisterRequest(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class CreateChatRequest(BaseModel):
    initiator: str
    participants: Union[str, List[str]]
    is_group: bool = False

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

@app.post("/register")
async def register(request: RegisterRequest):
    """User registration endpoint."""
    try:
        # Validate input
        if not request.username or not request.password:
            raise HTTPException(status_code=400, detail="Username and password are required")
        
        # Attempt to register user
        if user_manager.register_user(request.username, request.password):
            return {"message": "User registered successfully"}
        else:
            raise HTTPException(status_code=400, detail="Username already exists")
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="Registration failed")

@app.post("/login")
async def login(request: LoginRequest):
    """User login endpoint."""
    try:
        # Validate credentials
        if user_manager.validate_user(request.username, request.password):
            # Generate and return login token
            token = user_manager.generate_token(request.username)
            return {"token": token, "username": request.username}
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(status_code=500, detail="Login failed")

@app.post("/create-chat")
async def create_chat(request: CreateChatRequest):
    """Endpoint to create a new chat."""
    try:
        chat_id = user_manager.create_chat(
            request.initiator, 
            request.participants, 
            request.is_group
        )
        return {"chat_id": chat_id}
    except Exception as e:
        logger.error(f"Error creating chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user-chats/{username}")
async def get_user_chats(username: str):
    """Get all chats for a user."""
    return user_manager.get_user_chats(username)

@app.get("/chat-messages/{chat_id}")
async def get_chat_messages(chat_id: str):
    """Get messages for a specific chat."""
    return user_manager.get_chat_messages(chat_id)

@app.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    # Validate token first
    username = user_manager.validate_token(token)
    if not username:
        await websocket.close(code=1008, reason="Invalid token")
        return
    
    await websocket.accept()
    
    # Store the websocket connection
    active_connections[username] = websocket
    
    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            # Handle different types of WebSocket messages
            if message_data.get('type') == 'create_chat':
                # Create a new chat (support both single and group chats)
                initiator = message_data.get('initiator')
                participants = message_data.get('participants', [])
                is_group = message_data.get('is_group', False)
                
                chat_id = user_manager.create_chat(initiator, participants, is_group)
                
                await websocket.send_text(json.dumps({
                    'type': 'chat_created',
                    'chat_id': chat_id,
                    'participants': participants,
                    'is_group': is_group
                }))
            
            elif message_data.get('type') == 'send_message':
                # Send a message in a specific chat
                chat_id = message_data.get('chat_id')
                sender = message_data.get('sender')
                message = message_data.get('message')
                
                try:
                    # Add message to chat
                    message_entry = user_manager.add_message_to_chat(chat_id, sender, message)
                    
                    # Broadcast to all participants in the chat
                    chat = user_manager.chats_collection.find_one({'_id': ObjectId(chat_id)})
                    for participant in chat.get('participants', []):
                        if participant in active_connections:
                            await active_connections[participant].send_text(json.dumps({
                                'type': 'new_message',
                                'chat_id': chat_id,
                                'sender': sender,
                                'message': message,
                                'is_group': chat.get('is_group', False)
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
