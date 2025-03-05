class ChatApplication {
    constructor() {
        this.socket = null;
        this.username = null;
        this.token = null;
        this.currentChatId = null;
        this.chats = {};
    }

    showError(message, type = 'error') {
        const errorEl = document.getElementById('errorMessage');
        if (!errorEl) return;

        errorEl.textContent = message;
        errorEl.style.color = type === 'error' ? 'red' : 'green';
        errorEl.style.display = 'block';
        
        // Auto-hide error after 3 seconds
        setTimeout(() => {
            errorEl.textContent = '';
            errorEl.style.display = 'none';
        }, 3000);
    }

    register() {
        const usernameInput = document.getElementById('usernameInput');
        const passwordInput = document.getElementById('passwordInput');
        const username = usernameInput.value.trim();
        const password = passwordInput.value.trim();

        if (!username || !password) {
            this.showError('Please enter both username and password');
            return;
        }

        fetch('/register', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => { throw err; });
            }
            return response.json();
        })
        .then(data => {
            this.showError('Registration successful! Please log in.', 'success');
            // Clear inputs after successful registration
            usernameInput.value = '';
            passwordInput.value = '';
        })
        .catch(error => {
            console.error('Registration error:', error);
            this.showError(error.detail || 'Registration failed');
        });
    }

    login() {
        const usernameInput = document.getElementById('usernameInput');
        const passwordInput = document.getElementById('passwordInput');
        const username = usernameInput.value.trim();
        const password = passwordInput.value.trim();

        if (!username || !password) {
            this.showError('Please enter both username and password');
            return;
        }

        fetch('/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => { throw err; });
            }
            return response.json();
        })
        .then(data => {
            this.username = data.username;
            this.token = data.token;
            this.connect();
        })
        .catch(error => {
            console.error('Login error:', error);
            this.showError(error.detail || 'Login failed');
        });
    }

    connect() {
        // Determine WebSocket URL
        let wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        let wsHost = window.location.host;
        let wsUrl = `${wsProtocol}://${wsHost}/ws/${encodeURIComponent(this.token)}`;
        
        this.socket = new WebSocket(wsUrl);
        
        this.socket.onopen = () => {
            console.log('WebSocket connected');
            this.loadUserChats();
        };
        
        this.socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleWebSocketMessage(data);
        };
        
        this.socket.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.showLoginForm();
        };

        // Show chat section
        document.getElementById('loginSection').style.display = 'none';
        document.getElementById('chatSection').style.display = 'block';
    }

    handleWebSocketMessage(data) {
        switch(data.type) {
            case 'chat_created':
                this.onChatCreated(data);
                break;
            case 'new_message':
                this.onNewMessage(data);
                break;
            case 'error':
                this.showError(data.message);
                break;
        }
    }

    loadUserChats() {
        fetch(`/user-chats/${this.username}`)
            .then(response => response.json())
            .then(chats => {
                this.chats = chats;
                this.renderChatList();
            })
            .catch(error => {
                console.error('Error loading chats:', error);
                this.showError('Failed to load chats');
            });
    }

    renderChatList() {
        const chatList = document.getElementById('chatList');
        chatList.innerHTML = '';
        
        this.chats.forEach(chat => {
            const chatItem = document.createElement('div');
            chatItem.className = 'chat-item';
            
            // Display chat name differently for group and single chats
            const displayName = chat.is_group 
                ? chat.participant  // Assuming the chat name is set for group chats
                : chat.participant;
            
            chatItem.innerHTML = `
                <strong>${displayName}${chat.is_group ? ' (Group)' : ''}</strong>
                <p>${chat.last_message || 'No messages yet'}</p>
            `;
            chatItem.onclick = () => this.openChat(chat.chat_id, displayName);
            chatList.appendChild(chatItem);
        });
    }

    createNewChat() {
        const participantInput = document.getElementById('newChatParticipant');
        const participantString = participantInput.value.trim();
        
        if (!participantString) {
            this.showError('Please enter username(s)');
            return;
        }

        // Split participants by space, remove empty strings
        const participants = participantString.split(/\s+/).filter(p => p.length > 0);

        // Determine if it's a group chat based on number of participants
        const isGroup = participants.length > 1;

        // Send create chat message via WebSocket
        this.socket.send(JSON.stringify({
            type: 'create_chat',
            initiator: this.username,
            participants: isGroup ? participants : participants[0],
            is_group: isGroup
        }));

        // Clear input
        participantInput.value = '';
    }

    onChatCreated(data) {
        // Refresh chat list after creating a new chat
        this.loadUserChats();
        this.openChat(data.chat_id, data.participants);
    }

    openChat(chatId, displayName) {
        this.currentChatId = chatId;
        
        // Show messaging section
        const messagingSection = document.getElementById('messagingSection');
        messagingSection.style.display = 'block';
        
        // Fetch chat messages
        fetch(`/chat-messages/${chatId}`)
            .then(response => response.json())
            .then(messages => {
                this.renderChatMessages(messages, displayName);
            })
            .catch(error => {
                console.error('Error loading chat messages:', error);
                this.showError('Failed to load chat messages');
            });
    }

    renderChatMessages(messages, displayName) {
        const chatContainer = document.getElementById('chatMessages');
        const chatHeaderEl = document.getElementById('chatHeader');
        
        // Update chat header
        chatHeaderEl.innerHTML = `
            <h2>Chat with ${displayName}</h2>
        `;
        
        // Clear previous messages
        chatContainer.innerHTML = '';
        
        // Render messages
        messages.forEach(msg => {
            const messageEl = document.createElement('div');
            messageEl.className = `message ${msg.sender === this.username ? 'sent' : 'received'}`;
            messageEl.textContent = `${msg.sender}: ${msg.message}`;
            chatContainer.appendChild(messageEl);
        });

        // Scroll to bottom of messages
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    sendMessage() {
        const messageInput = document.getElementById('messageInput');
        const message = messageInput.value.trim();
        
        if (!message || !this.currentChatId) {
            this.showError('Please select a chat and enter a message');
            return;
        }

        // Send message via WebSocket
        this.socket.send(JSON.stringify({
            type: 'send_message',
            chat_id: this.currentChatId,
            sender: this.username,
            message: message
        }));

        // Clear input
        messageInput.value = '';
    }

    onNewMessage(data) {
        // If the message is for the current open chat, update messages
        if (data.chat_id === this.currentChatId) {
            const chatContainer = document.getElementById('chatMessages');
            const messageEl = document.createElement('div');
            messageEl.className = `message ${data.sender === this.username ? 'sent' : 'received'}`;
            messageEl.textContent = `${data.sender}: ${data.message}`;
            chatContainer.appendChild(messageEl);
            
            // Scroll to bottom of messages
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }
        
        // Refresh chat list to update last message
        this.loadUserChats();
    }

    showLoginForm() {
        document.getElementById('loginSection').style.display = 'block';
        document.getElementById('chatSection').style.display = 'none';
        document.getElementById('usernameInput').value = '';
        document.getElementById('passwordInput').value = '';
        
        // Reset application state
        this.socket = null;
        this.username = null;
        this.token = null;
        this.currentChatId = null;
        this.chats = {};

        // Clear any error messages
        this.clearError();
    }

    showError(message, type = 'error') {
        const errorEl = document.getElementById('errorMessage');
        errorEl.textContent = message;
        errorEl.className = type === 'success' ? 'success-message' : 'error-message';
        errorEl.style.display = 'block';
        
        // Auto-hide error after 3 seconds
        setTimeout(() => {
            this.clearError();
        }, 3000);
    }

    clearError() {
        const errorEl = document.getElementById('errorMessage');
        errorEl.textContent = '';
        errorEl.style.display = 'none';
    }
}

// Initialize chat application
const chatApp = new ChatApplication();

function registerUser() {
    chatApp.register();
}

function loginUser() {
    chatApp.login();
}

function logout() {
    chatApp.showLoginForm();
}
