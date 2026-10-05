"use client";

import { useState, useCallback, useRef } from "react";
import Header from "@/components/Header";
import ChatPage from "@/components/ChatPage";
import DocumentSidebar from "@/components/DocumentSidebar";
import type { Message } from "@/lib/types";
import { sendMessage } from "@/lib/chatApi";

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const sessionIdRef = useRef<string | undefined>(undefined);

  const handleSend = useCallback(async (text: string) => {
    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    try {
      // Snapshot history before the new user message (setMessages is async)
      const history = messages.map(({ role, content }) => ({ role, content }));

      const response = await sendMessage(text, history, sessionIdRef.current);

      // Persist session ID for stateful backends
      if (response.session_id) {
        sessionIdRef.current = response.session_id;
      }

      const aiMessage: Message = {
        id: `ai-${Date.now()}`,
        role: "assistant",
        content: response.reply,
        timestamp: new Date().toISOString(),
        sources: response.metadata?.sources,
        clarification: response.metadata?.clarification,
      };

      setMessages((prev) => [...prev, aiMessage]);
    } catch (err) {
      console.error("[chat] API call failed:", err);

      const errorContent = "Sorry, I couldn't reach the assistant. Please check that the backend is running and try again.";

      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: "assistant",
          content: errorContent,
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [messages]);

  // Clarification button selection — sends the selected option value to backend without adding a user bubble
  const handleClarificationSelect = useCallback(async (selectedValue: string) => {
    setIsLoading(true);
    try {
      const history = messages.map(({ role, content }) => ({ role, content }));
      const response = await sendMessage(selectedValue, history, sessionIdRef.current);
      if (response.session_id) {
        sessionIdRef.current = response.session_id;
      }
      setMessages((prev) => [
        ...prev,
        {
          id: `ai-${Date.now()}`,
          role: "assistant",
          content: response.reply,
          timestamp: new Date().toISOString(),
          sources: response.metadata?.sources,
          clarification: response.metadata?.clarification,
        },
      ]);
    } catch (err) {
      console.error("[chat] clarification API call failed:", err);
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: "assistant",
          content: "Sorry, I couldn't reach the assistant. Please check that the backend is running and try again.",
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [messages]);

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <Header onDocsClick={() => setIsSidebarOpen(true)} />

      <DocumentSidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
      />

      <ChatPage
          messages={messages}
          onSend={handleSend}
          onClarificationSelect={handleClarificationSelect}
          isLoading={isLoading}
      />
    </div>
  );
}
