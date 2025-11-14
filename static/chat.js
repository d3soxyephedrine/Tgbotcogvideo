// Create floating particles
const particlesContainer = document.getElementById('particles');
for (let i = 0; i < 30; i++) {
    const particle = document.createElement('div');
    particle.className = 'particle';
    particle.style.left = Math.random() * 100 + '%';
    particle.style.animationDelay = Math.random() * 15 + 's';
    particle.style.animationDuration = (Math.random() * 10 + 10) + 's';
    particlesContainer.appendChild(particle);
}

const API_ENDPOINT = '/v1/chat/completions';
let apiKey = localStorage.getItem('uncensored_ai_api_key') || '';
let conversationHistory = [];
let currentConversationId = null;
let conversations = [];

const chatArea = document.getElementById('chat-area');
const messageInput = document.getElementById('message-input');
const sendButton = document.getElementById('send-button');
const typingIndicator = document.getElementById('typing-indicator');
const apiKeyModal = document.getElementById('api-key-modal');
const apiKeyInput = document.getElementById('api-key-input');
const saveApiKeyButton = document.getElementById('save-api-key');
const creditBadge = document.getElementById('credit-badge');
const conversationsList = document.getElementById('conversations-list');
const newChatBtn = document.getElementById('new-chat-btn');
const menuToggle = document.getElementById('menu-toggle');
const sidebar = document.getElementById('sidebar');
const sidebarBackdrop = document.getElementById('sidebar-backdrop');

// Defensive check for menu toggle
if (!menuToggle) {
    console.error('Menu toggle button not found');
}

// Show/hide API key modal and load conversations
if (!apiKey) {
    apiKeyModal.style.display = 'flex';
} else {
    apiKeyModal.style.display = 'none';
    updateCreditBalance();
    loadConversations();
}

// Toast notification function
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'toastSlideOut 0.3s ease-out';
        setTimeout(() => {
            document.body.removeChild(toast);
        }, 300);
    }, 3000);
}

// Save API key
saveApiKeyButton.addEventListener('click', () => {
    const key = apiKeyInput.value.trim();
    if (key) {
        apiKey = key;
        localStorage.setItem('uncensored_ai_api_key', key);
        apiKeyModal.style.display = 'none';
        updateCreditBalance();
        loadConversations();
        showToast('API key saved successfully!', 'success');
    } else {
        showToast('Please enter a valid API key', 'error');
    }
});

// New chat button
newChatBtn.addEventListener('click', createNewConversation);

// Mobile menu toggle
if (menuToggle) {
    menuToggle.addEventListener('click', () => {
        sidebar.classList.toggle('active');
        sidebarBackdrop.classList.toggle('active');
    });
}

// Close sidebar when clicking backdrop
if (sidebarBackdrop) {
    sidebarBackdrop.addEventListener('click', () => {
        sidebar.classList.remove('active');
        sidebarBackdrop.classList.remove('active');
    });
}

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    // Escape to close sidebar
    if (e.key === 'Escape') {
        if (sidebar.classList.contains('active')) {
            sidebar.classList.remove('active');
            sidebarBackdrop.classList.remove('active');
        }
    }

    // Ctrl+K for new chat
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        createNewConversation();
    }
});

// Allow Enter to save API key
apiKeyInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        saveApiKeyButton.click();
    }
});

// Auto-resize textarea
messageInput.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 200) + 'px';
});

// Send message on Enter (Shift+Enter for new line)
messageInput.addEventListener('keypress', async (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        await sendMessage();
    }
});

sendButton.addEventListener('click', sendMessage);

async function updateCreditBalance() {
    if (!apiKey) {
        creditBadge.textContent = 'Credits: --';
        return;
    }

    try {
        const response = await fetch('/api/balance', {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${apiKey}`
            }
        });

        if (response.ok) {
            const data = await response.json();
            creditBadge.textContent = `Credits: ${data.total_credits}`;
        } else {
            creditBadge.textContent = 'Credits: --';
        }
    } catch (error) {
        console.error('Failed to fetch balance:', error);
        creditBadge.textContent = 'Credits: --';
    }
}

async function loadConversations() {
    if (!apiKey) return;

    try {
        const response = await fetch('/api/conversations', {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${apiKey}`
            }
        });

        if (response.ok) {
            const data = await response.json();
            conversations = data.conversations || [];

            renderConversations();

            // Select first conversation or create one if none exist
            if (conversations.length > 0) {
                switchConversation(conversations[0].id);
            } else {
                // Auto-create first conversation
                await createNewConversation();
            }
        } else if (response.status === 401) {
            console.error('Invalid API key');
            localStorage.removeItem('uncensored_ai_api_key');
            location.reload();
        }
    } catch (error) {
        console.error('Failed to load conversations:', error);
    }
}

function renderConversations() {
    conversationsList.innerHTML = '';

    conversations.forEach(conv => {
        const convDiv = document.createElement('div');
        convDiv.className = 'conversation-item';
        if (conv.id === currentConversationId) {
            convDiv.classList.add('active');
        }

        convDiv.innerHTML = `
            <div class="conversation-title">${conv.title}</div>
            <div class="conversation-meta">
                <span>${conv.message_count} messages</span>
            </div>
            <button class="delete-conversation-btn" onclick="event.stopPropagation(); deleteConversation(${conv.id})">
                Delete
            </button>
        `;

        convDiv.onclick = () => switchConversation(conv.id);
        conversationsList.appendChild(convDiv);
    });
}

async function createNewConversation() {
    if (!apiKey) {
        console.error('No API key available');
        return;
    }

    try {
        console.log('Creating new conversation...');
        const response = await fetch('/api/conversations', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${apiKey}`
            },
            body: JSON.stringify({
                title: 'New Chat'
            })
        });

        console.log('Response status:', response.status);

        if (response.ok) {
            const newConv = await response.json();
            console.log('Created new conversation:', newConv);
            conversations.unshift(newConv);
            renderConversations();
            await switchConversation(newConv.id);
            showToast('New chat created!', 'success');
        } else {
            const error = await response.json();
            console.error('Failed to create conversation:', error);
            showToast('Failed to create new chat: ' + (error.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('Failed to create conversation:', error);
        showToast('Failed to create new chat. Please try again.', 'error');
    }
}

async function switchConversation(conversationId) {
    currentConversationId = conversationId;
    renderConversations();

    // Clear chat area and load messages for this conversation
    chatArea.innerHTML = '';
    conversationHistory = [];

    await loadMessageHistory(conversationId);

    // Close sidebar on mobile after switching
    sidebar.classList.remove('active');
    sidebarBackdrop.classList.remove('active');
}

async function deleteConversation(conversationId) {
    // Find conversation details for better confirmation
    const conv = conversations.find(c => c.id === conversationId);
    const convTitle = conv ? conv.title : 'this conversation';
    const msgCount = conv ? conv.message_count : 0;

    if (!confirm(`Delete "${convTitle}" (${msgCount} messages)?\n\nThis cannot be undone.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/conversations/${conversationId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${apiKey}`
            }
        });

        if (response.ok) {
            showToast('Conversation deleted', 'success');
            // Remove from local array
            conversations = conversations.filter(c => c.id !== conversationId);
            renderConversations();

            // If deleted current conversation, switch to another
            if (conversationId === currentConversationId) {
                if (conversations.length > 0) {
                    switchConversation(conversations[0].id);
                } else {
                    // Create new conversation if none left
                    await createNewConversation();
                }
            }
        } else {
            showToast('Failed to delete conversation', 'error');
        }
    } catch (error) {
        console.error('Failed to delete conversation:', error);
        showToast('Failed to delete conversation', 'error');
    }
}

async function loadMessageHistory(conversationId) {
    if (!apiKey || !conversationId) return;

    try {
        const response = await fetch(`/api/messages?conversation_id=${conversationId}`, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${apiKey}`
            }
        });

        if (response.ok) {
            const data = await response.json();
            const messages = data.messages || [];

            // Display all messages
            messages.forEach(msg => {
                addMessage(msg.role, msg.content);
            });

            // Populate conversation history for context
            conversationHistory = messages;

            console.log(`Loaded ${messages.length} messages from conversation ${conversationId}`);
            scrollToBottom();
        } else if (response.status === 401) {
            console.error('Invalid API key when loading messages');
            localStorage.removeItem('uncensored_ai_api_key');
            location.reload();
        }
    } catch (error) {
        console.error('Failed to load message history:', error);
    }
}

async function sendMessage() {
    const message = messageInput.value.trim();
    if (!message || !apiKey) return;

    // Disable input and show loading state
    messageInput.disabled = true;
    sendButton.disabled = true;
    sendButton.classList.add('loading');

    // Add user message to chat
    addMessage('user', message);
    messageInput.value = '';
    messageInput.style.height = 'auto';

    // Add to conversation history
    conversationHistory.push({
        role: 'user',
        content: message
    });

    // Show typing indicator
    typingIndicator.classList.add('active');
    scrollToBottom();

    try {
        const response = await fetch(API_ENDPOINT, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${apiKey}`
            },
            body: JSON.stringify({
                model: 'openai/chatgpt-4o-latest',
                messages: conversationHistory,
                stream: true,
                conversation_id: currentConversationId
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error?.message || 'Request failed');
        }

        // Handle streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let assistantMessage = '';
        let messageElement = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.substring(6);
                    if (data === '[DONE]') continue;

                    try {
                        const parsed = JSON.parse(data);
                        const content = parsed.choices?.[0]?.delta?.content;

                        if (content) {
                            assistantMessage += content;

                            // Create or update message element
                            if (!messageElement) {
                                typingIndicator.classList.remove('active');
                                messageElement = addMessage('assistant', assistantMessage);
                            } else {
                                messageElement.textContent = assistantMessage;
                            }

                            scrollToBottom();
                        }
                    } catch (e) {
                        // Ignore parsing errors for incomplete chunks
                    }
                }
            }
        }

        // Add assistant response to history
        if (assistantMessage) {
            conversationHistory.push({
                role: 'assistant',
                content: assistantMessage
            });
        }

    } catch (error) {
        console.error('Error:', error);
        typingIndicator.classList.remove('active');

        if (error.message.includes('Invalid API key')) {
            addMessage('error', '❌ Invalid API key. Get a new one from Telegram: /getapikey');
            localStorage.removeItem('uncensored_ai_api_key');
            apiKey = '';
            setTimeout(() => {
                location.reload();
            }, 2000);
        } else if (error.message.includes('Insufficient credits')) {
            addMessage('error', '❌ ' + error.message);
        } else {
            addMessage('error', '❌ Error: ' + error.message);
        }
    } finally {
        // Re-enable input and remove loading state
        messageInput.disabled = false;
        sendButton.disabled = false;
        sendButton.classList.remove('loading');
        messageInput.focus();
        typingIndicator.classList.remove('active');

        // Update credit balance after message
        updateCreditBalance();

        // Reload conversations to get updated titles
        await loadConversations();
    }
}

function addMessage(type, content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;
    messageDiv.textContent = content;
    chatArea.appendChild(messageDiv);
    scrollToBottom();
    return messageDiv;
}

function scrollToBottom() {
    chatArea.scrollTop = chatArea.scrollHeight;
}

// Focus input on load
if (apiKey) {
    messageInput.focus();
}
