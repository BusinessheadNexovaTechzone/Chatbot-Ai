/**
 * Example: JavaScript/TypeScript client for Nexo Chatbot API
 * Works in both browser and Node.js environments
 */

class NexoChatbotClient {
  constructor(apiUrl = "http://localhost:8081/api/v1", assistantName = "Assistant") {
    this.apiUrl = apiUrl;
    this.assistantName = assistantName;
    this.sessionId = this.generateSessionId();
  }

  generateSessionId() {
    return `session_${Math.random().toString(36).substr(2, 9)}`;
  }

  /**
   * Send a chat message and get a response
   * @param {string} query - User's question
   * @param {boolean} stream - Whether to stream the response
   * @returns {Promise<Object>} Response with answer, intent, sources, etc.
   */
  async chat(query, stream = false) {
    const payload = {
      query,
      session_id: this.sessionId,
      assistant_name: this.assistantName,
      stream,
    };

    if (stream) {
      return await this._streamChat(payload);
    } else {
      return await this._chatNormal(payload);
    }
  }

  /**
   * Non-streaming chat request
   * @private
   */
  async _chatNormal(payload) {
    const response = await fetch(`${this.apiUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.statusText}`);
    }

    return await response.json();
  }

  /**
   * Streaming chat request using Server-Sent Events
   * @private
   */
  async _streamChat(payload) {
    return new Promise((resolve, reject) => {
      let fullResponse = "";

      const eventSource = new EventSource(
        `${this.apiUrl}/chat/stream?${new URLSearchParams(payload)}`
      );

      eventSource.onmessage = (event) => {
        if (event.data === "[DONE]") {
          eventSource.close();
          resolve({ answer: fullResponse });
        } else if (event.data.startsWith("[ERROR]")) {
          eventSource.close();
          reject(new Error(event.data));
        } else {
          fullResponse += event.data;
          process.stdout.write(event.data); // For Node.js
        }
      };

      eventSource.onerror = (error) => {
        eventSource.close();
        reject(error);
      };
    });
  }

  /**
   * Health check
   */
  async healthCheck() {
    const baseUrl = this.apiUrl.replace("/api/v1", "");
    const response = await fetch(`${baseUrl}/v1/health`);

    if (!response.ok) {
      throw new Error(`Health check failed: ${response.statusText}`);
    }

    return await response.json();
  }

  /**
   * Upload a file
   * @param {File} file - File to upload
   */
  async uploadFile(file) {
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(`${this.apiUrl}/upload`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Upload failed: ${response.statusText}`);
    }

    return await response.json();
  }

  /**
   * Ingest URLs
   * @param {string[]} urls - URLs to scrape
   * @param {string} siteName - Name of the site
   */
  async ingestUrls(urls, siteName) {
    const payload = {
      urls,
      site_name: siteName,
      force_refresh: false,
    };

    const response = await fetch(`${this.apiUrl}/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Ingestion failed: ${response.statusText}`);
    }

    return await response.json();
  }

  /**
   * Connect to WebSocket for real-time chat
   * @returns {WebSocket}
   */
  connectWebSocket() {
    const wsUrl = this.apiUrl.replace("http", "ws").replace("/api/v1", "");
    const ws = new WebSocket(`${wsUrl}/v1/ws/web_chat/${this.sessionId}`);

    ws.onopen = () => {
      console.log("WebSocket connected");
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
    };

    ws.onclose = () => {
      console.log("WebSocket disconnected");
    };

    return ws;
  }

  /**
   * Send a message via WebSocket
   */
  sendWebSocketMessage(ws, query) {
    const message = {
      query,
      assistant_name: this.assistantName,
    };
    ws.send(JSON.stringify(message));
  }
}

// ============================================================================
// EXAMPLES
// ============================================================================

/**
 * Example 1: Basic Chat
 */
async function example1_basicChat() {
  console.log("\n=== Example 1: Basic Chat ===\n");

  const client = new NexoChatbotClient("http://localhost:8081/api/v1", "John");

  try {
    // Question 1
    let response = await client.chat("What is your name?");
    console.log("Q: What is your name?");
    console.log(`A: ${response.answer}`);
    console.log(`Intent: ${response.intent}`);
    console.log(`Latency: ${response.latency_ms}ms\n`);

    // Question 2
    response = await client.chat("Tell me a joke");
    console.log("Q: Tell me a joke");
    console.log(`A: ${response.answer}`);
    console.log(`Intent: ${response.intent}\n`);
  } catch (error) {
    console.error("Error:", error.message);
  }
}

/**
 * Example 2: Conversation Memory
 */
async function example2_conversationMemory() {
  console.log("\n=== Example 2: Conversation Memory ===\n");

  const client = new NexoChatbotClient("http://localhost:8081/api/v1", "Alice");

  try {
    // Turn 1
    let response = await client.chat("My name is Dinesh Sharma");
    console.log("Turn 1:");
    console.log("  Q: My name is Dinesh Sharma");
    console.log(`  A: ${response.answer}\n`);

    // Turn 2
    response = await client.chat("What is my name?");
    console.log("Turn 2:");
    console.log("  Q: What is my name?");
    console.log(`  A: ${response.answer}`);
    console.log("  (Note: Memory working - assistant recalls your name)\n");

    // Turn 3
    response = await client.chat("Who are you?");
    console.log("Turn 3:");
    console.log("  Q: Who are you?");
    console.log(`  A: ${response.answer}\n`);
  } catch (error) {
    console.error("Error:", error.message);
  }
}

/**
 * Example 3: Streaming Response
 */
async function example3_streaming() {
  console.log("\n=== Example 3: Streaming Response ===\n");

  const client = new NexoChatbotClient("http://localhost:8081/api/v1", "Bob");

  try {
    console.log("Q: Explain machine learning in a few paragraphs");
    console.log("A: ", "");

    await client.chat("Explain machine learning in a few paragraphs", true);

    console.log("\n");
  } catch (error) {
    console.error("Error:", error.message);
  }
}

/**
 * Example 4: Different Assistant Names
 */
async function example4_differentAssistants() {
  console.log("\n=== Example 4: Different Assistant Names ===\n");

  const assistants = ["Emma", "David", "Sara"];

  try {
    for (const name of assistants) {
      const client = new NexoChatbotClient("http://localhost:8081/api/v1", name);
      const response = await client.chat("Who are you?");
      console.log(`Assistant: ${name}`);
      console.log(`  Response: ${response.answer}\n`);
    }
  } catch (error) {
    console.error("Error:", error.message);
  }
}

/**
 * Example 5: WebSocket Real-time Chat
 */
async function example5_webSocket() {
  console.log("\n=== Example 5: WebSocket Real-time Chat ===\n");

  const client = new NexoChatbotClient("http://localhost:8081/api/v1", "Charlie");
  const ws = client.connectWebSocket();

  return new Promise((resolve) => {
    ws.onopen = () => {
      console.log("Connected to WebSocket\n");

      // Send first message
      client.sendWebSocketMessage(ws, "What is your name?");

      let messageCount = 0;

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === "token") {
          process.stdout.write(data.data);
        } else if (data.type === "result") {
          console.log("\n\nFinal response received\n");
          messageCount++;

          if (messageCount < 2) {
            // Send another message
            client.sendWebSocketMessage(ws, "Tell me about your capabilities");
          } else {
            ws.close();
            resolve();
          }
        }
      };
    };
  });
}

/**
 * Example 6: Health Check
 */
async function example6_healthCheck() {
  console.log("\n=== Example 6: Health Check ===\n");

  const client = new NexoChatbotClient();

  try {
    const health = await client.healthCheck();
    console.log(`Status: ${health.status}`);
    console.log(`Version: ${health.version}`);
    console.log("Components:");
    for (const [component, status] of Object.entries(health.components)) {
      console.log(`  ${component}: ${status}`);
    }
  } catch (error) {
    console.error("Error:", error.message);
  }
}

/**
 * Example 7: File Upload
 */
async function example7_fileUpload() {
  console.log("\n=== Example 7: File Upload ===\n");

  const client = new NexoChatbotClient();

  // This example assumes we're in a browser environment with a file input
  // In Node.js, you would need to use a File-like object

  console.log("Note: File upload example requires browser environment with file input");
  console.log("In React, you would handle it like this:");
  console.log(`
    const handleFileUpload = async (event) => {
      const file = event.target.files[0];
      const response = await client.uploadFile(file);
      console.log('Upload response:', response);
    };
  `);
}

/**
 * Example 8: HTML Chat Interface
 */
function example8_htmlInterface() {
  const htmlCode = `
<!DOCTYPE html>
<html>
<head>
  <title>Nexo Chatbot</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      max-width: 800px;
      margin: 0 auto;
      padding: 20px;
      background: #f5f5f5;
    }
    .chat-container {
      background: white;
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    }
    .messages {
      height: 400px;
      overflow-y: auto;
      margin-bottom: 20px;
      padding: 10px;
      border: 1px solid #ddd;
      border-radius: 4px;
    }
    .message {
      margin: 10px 0;
      padding: 10px;
      border-radius: 4px;
    }
    .user-message {
      background: #e3f2fd;
      text-align: right;
    }
    .assistant-message {
      background: #f1f1f1;
    }
    .input-group {
      display: flex;
      gap: 10px;
    }
    input, button {
      padding: 10px;
      border: 1px solid #ddd;
      border-radius: 4px;
      font-size: 14px;
    }
    input {
      flex: 1;
    }
    button {
      background: #2196F3;
      color: white;
      border: none;
      cursor: pointer;
    }
    button:hover {
      background: #1976D2;
    }
  </style>
</head>
<body>
  <div class="chat-container">
    <h1>Nexo Chatbot</h1>
    <div class="messages" id="messages"></div>
    <div class="input-group">
      <input type="text" id="query" placeholder="Ask me anything..." />
      <button onclick="sendMessage()">Send</button>
    </div>
  </div>

  <script src="path/to/nexo-chatbot-client.js"></script>
  <script>
    const client = new NexoChatbotClient(
      "http://localhost:8081/api/v1",
      "Assistant"
    );

    async function sendMessage() {
      const query = document.getElementById("query").value;
      if (!query.trim()) return;

      const messagesDiv = document.getElementById("messages");

      // Add user message
      const userMsg = document.createElement("div");
      userMsg.className = "message user-message";
      userMsg.textContent = query;
      messagesDiv.appendChild(userMsg);
      messagesDiv.scrollTop = messagesDiv.scrollHeight;

      document.getElementById("query").value = "";

      try {
        // Get response with streaming
        const response = await client.chat(query, true);

        // Add assistant message
        const assistantMsg = document.createElement("div");
        assistantMsg.className = "message assistant-message";
        assistantMsg.textContent = response.answer;
        messagesDiv.appendChild(assistantMsg);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
      } catch (error) {
        const errorMsg = document.createElement("div");
        errorMsg.className = "message assistant-message";
        errorMsg.textContent = "Error: " + error.message;
        messagesDiv.appendChild(errorMsg);
      }
    }

    // Allow Enter key to send message
    document.getElementById("query").addEventListener("keypress", (e) => {
      if (e.key === "Enter") sendMessage();
    });
  </script>
</body>
</html>
  `;

  console.log("\n=== Example 8: HTML Chat Interface ===\n");
  console.log("Save this HTML code to test the chatbot UI:");
  console.log(htmlCode);
}

// ============================================================================
// MAIN - Run examples
// ============================================================================

async function runAllExamples() {
  console.log("=".repeat(60));
  console.log("Nexo Chatbot API - JavaScript Client Examples");
  console.log("=".repeat(60));

  // Uncomment examples to run:
  // await example1_basicChat();
  // await example2_conversationMemory();
  // await example3_streaming();
  // await example4_differentAssistants();
  // await example5_webSocket();
  // await example6_healthCheck();
  // example7_fileUpload();
  // example8_htmlInterface();

  console.log("\n" + "=".repeat(60));
  console.log("Examples ready to run!");
  console.log("Uncomment the examples you want to test in the code.");
  console.log("=".repeat(60));
}

// Export for use as module
if (typeof module !== "undefined" && module.exports) {
  module.exports = NexoChatbotClient;
}

// Run examples if executed directly
if (typeof window === "undefined" && require.main === module) {
  runAllExamples();
}
