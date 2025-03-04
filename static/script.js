class ChatApplication {
    constructor() {
        this.socket = null;
        this.username = null;
        this.currentChatId = null;
        this.chats = {};
    }

    connect(username) {
        this.username = username;
        
        // Determine WebSocket URL
        let wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        let wsHost = window.location.host;
        let wsUrl = `${wsProtocol}://${wsHost}/ws/${encodeURIComponent(username)}`;
        
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
        };
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
            });
    }

    renderChatList() {
        const chatList = document.getElementById('chatList');
        chatList.innerHTML = '';
        
        this.chats.forEach(chat => {
            const chatItem = document.createElement('div');
            chatItem.className = 'chat-item';
            chatItem.innerHTML = `
                <strong>${chat.participant}</strong>
                <p>${chat.last_message || 'No messages yet'}</p>
            `;
            chatItem.onclick = () => this.openChat(chat.chat_id, chat.participant);
            chatList.appendChild(chatItem);
        });
    }

    createNewChat() {
        const participantInput = document.getElementById('newChatParticipant');
        const participant = participantInput.value.trim();
        
        if (!participant) {
            alert('Please enter a username');
            return;
        }

        // Send create chat message via WebSocket
        this.socket.send(JSON.stringify({
            type: 'create_chat',
            initiator: this.username,
            participant: participant
        }));
    }

    onChatCreated(data) {
        // Refresh chat list after creating a new chat
        this.loadUserChats();
        this.openChat(data.chat_id, data.participant);
    }

    openChat(chatId, participant) {
        this.currentChatId = chatId;
        
        // Show messaging section
        const messagingSection = document.getElementById('messagingSection');
        messagingSection.style.display = 'block';
        
        // Fetch chat messages
        fetch(`/chat-messages/${chatId}`)
            .then(response => response.json())
            .then(messages => {
                this.renderChatMessages(messages, participant);
            })
            .catch(error => {
                console.error('Error loading chat messages:', error);
            });
    }

    renderChatMessages(messages, participant) {
        const chatContainer = document.getElementById('chatMessages');
        const chatHeaderEl = document.getElementById('chatHeader');
        
        // Update chat header
        chatHeaderEl.innerHTML = `
            <h2>Chat with ${participant}</h2>
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
            alert('Please select a chat and enter a message');
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

    showError(message) {
        const errorEl = document.getElementById('errorMessage');
        errorEl.textContent = message;
        errorEl.style.display = 'block';
        setTimeout(() => {
            errorEl.style.display = 'none';
        }, 3000);
    }
}

// Initialize chat application
const chatApp = new ChatApplication();

function connectUser() {
    const usernameInput = document.getElementById('usernameInput');
    const username = usernameInput.value.trim();
    
    if (username) {
        chatApp.connect(username);
        document.getElementById('loginSection').style.display = 'none';
        document.getElementById('chatSection').style.display = 'block';
    } else {
        alert('Please enter a username');
    }
}
