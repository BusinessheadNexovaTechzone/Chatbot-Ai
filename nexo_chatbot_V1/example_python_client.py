#!/usr/bin/env python3
"""
Example: Python client for the Nexo Chatbot API.
Demonstrates all major endpoints with assistant name support.
"""

import asyncio
import json
import httpx
import uuid
from typing import Optional

# Configuration
API_BASE_URL = "http://localhost:8081/api/v1"
WS_BASE_URL = "ws://localhost:8081"
ASSISTANT_NAME = "John"


class NexoChatbotClient:
    """Async client for Nexo Chatbot API."""

    def __init__(self, api_url: str = API_BASE_URL, assistant_name: str = ASSISTANT_NAME):
        self.api_url = api_url
        self.assistant_name = assistant_name
        self.session_id = str(uuid.uuid4())  # Generate a unique session ID
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def chat(self, query: str, stream: bool = False) -> dict:
        """
        Send a chat message and get a response.

        Args:
            query: User's question
            stream: Whether to stream the response

        Returns:
            Response dictionary with answer, intent, sources, etc.
        """
        payload = {
            "query": query,
            "session_id": self.session_id,
            "assistant_name": self.assistant_name,
            "stream": stream,
        }

        if stream:
            return await self._stream_chat(payload)
        else:
            return await self._chat_normal(payload)

    async def _chat_normal(self, payload: dict) -> dict:
        """Non-streaming chat request."""
        response = await self.client.post(f"{self.api_url}/chat", json=payload)
        response.raise_for_status()
        return response.json()

    async def _stream_chat(self, payload: dict) -> dict:
        """Streaming chat request (SSE)."""
        full_response = ""

        async with self.client.stream("POST", f"{self.api_url}/chat/stream", json=payload) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    token = line[6:]  # Remove "data: " prefix
                    if token == "[DONE]":
                        break
                    if token == "[ERROR]":
                        raise RuntimeError("Stream error")
                    full_response += token
                    print(token, end="", flush=True)

        print()  # New line after streaming
        return {"answer": full_response}

    async def get_conversation_history(self) -> list:
        """
        Get the session's conversation history.
        Note: This endpoint is not exposed in the API, so we demonstrate
        how to maintain local history instead.
        """
        # For now, applications should maintain their own history
        # or implement a GET endpoint on the backend
        return []

    async def upload_file(self, filepath: str) -> dict:
        """
        Upload a document for indexing.

        Args:
            filepath: Path to the file to upload

        Returns:
            Response with file metadata
        """
        with open(filepath, "rb") as f:
            files = {"file": (filepath.split("/")[-1], f)}
            response = await self.client.post(f"{self.api_url}/upload", files=files)
            response.raise_for_status()
            return response.json()

    async def ingest_urls(self, urls: list, site_name: str) -> dict:
        """
        Scrape and index websites.

        Args:
            urls: List of URLs to scrape
            site_name: Name of the website/company

        Returns:
            Response with ingestion stats
        """
        payload = {"urls": urls, "site_name": site_name, "force_refresh": False}

        response = await self.client.post(f"{self.api_url}/ingest", json=payload)
        response.raise_for_status()
        return response.json()

    async def health_check(self) -> dict:
        """Check API and service health."""
        response = await self.client.get(f"{self.api_url.replace('/api/v1', '')}/v1/health")
        response.raise_for_status()
        return response.json()


async def example_basic_chat():
    """Example 1: Basic chat with assistant name."""
    print("\n=== Example 1: Basic Chat ===\n")

    client = NexoChatbotClient(assistant_name="John")

    try:
        # Question 1: Ask the assistant's name
        response = await client.chat("What is your name?")
        print(f"Q: What is your name?")
        print(f"A: {response['answer']}")
        print(f"Intent: {response['intent']}")
        print(f"Latency: {response['latency_ms']}ms\n")

        # Question 2: Another question
        response = await client.chat("Tell me a joke")
        print(f"Q: Tell me a joke")
        print(f"A: {response['answer']}")
        print(f"Intent: {response['intent']}\n")

        await client.close()
    except Exception as e:
        print(f"Error: {e}")


async def example_conversation_memory():
    """Example 2: Conversation memory across multiple turns."""
    print("\n=== Example 2: Conversation Memory ===\n")

    client = NexoChatbotClient(assistant_name="Alice")

    try:
        # Turn 1: User introduces themselves
        response = await client.chat("My name is Dinesh Sharma")
        print(f"Turn 1:")
        print(f"  Q: My name is Dinesh Sharma")
        print(f"  A: {response['answer']}\n")

        # Turn 2: Ask the assistant to recall the name
        response = await client.chat("What is my name?")
        print(f"Turn 2:")
        print(f"  Q: What is my name?")
        print(f"  A: {response['answer']}")
        print(f"  (Note: Memory working - assistant recalls your name)\n")

        # Turn 3: Ask about the assistant
        response = await client.chat("Who are you?")
        print(f"Turn 3:")
        print(f"  Q: Who are you?")
        print(f"  A: {response['answer']}\n")

        await client.close()
    except Exception as e:
        print(f"Error: {e}")


async def example_streaming():
    """Example 3: Streaming response."""
    print("\n=== Example 3: Streaming Response ===\n")

    client = NexoChatbotClient(assistant_name="Bob")

    try:
        print("Q: Explain machine learning in a few paragraphs")
        print("A: ", end="", flush=True)

        response = await client.chat("Explain machine learning in a few paragraphs", stream=True)

        await client.close()
    except Exception as e:
        print(f"Error: {e}")


async def example_different_assistants():
    """Example 4: Same session with different assistant names."""
    print("\n=== Example 4: Different Assistant Names ===\n")

    try:
        # Create clients with different names
        clients = [
            NexoChatbotClient(assistant_name="Emma"),
            NexoChatbotClient(assistant_name="David"),
            NexoChatbotClient(assistant_name="Sara"),
        ]

        for client in clients:
            response = await client.chat("Who are you?")
            print(f"Assistant: {client.assistant_name}")
            print(f"  Response: {response['answer']}\n")

            await client.close()

    except Exception as e:
        print(f"Error: {e}")


async def example_health_check():
    """Example 5: Health check."""
    print("\n=== Example 5: Health Check ===\n")

    client = NexoChatbotClient()

    try:
        health = await client.health_check()
        print(f"Status: {health['status']}")
        print(f"Version: {health['version']}")
        print(f"Components:")
        for component, status in health['components'].items():
            print(f"  {component}: {status}")

        await client.close()
    except Exception as e:
        print(f"Error: {e}")


async def main():
    """Run all examples."""
    print("=" * 60)
    print("Nexo Chatbot API - Python Client Examples")
    print("=" * 60)

    await example_basic_chat()
    await example_conversation_memory()
    await example_streaming()
    await example_different_assistants()
    await example_health_check()

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
