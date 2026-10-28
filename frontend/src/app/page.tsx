"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import Header from "@/components/Header";
import WelcomePage from "@/components/WelcomePage";
import ChatPage from "@/components/ChatPage";
import DocumentSidebar from "@/components/DocumentSidebar";
import type { Message } from "@/lib/types";
import { rewriteFeedback } from "@/lib/feedbackApi";
import { sendMessage } from "@/lib/chatApi";

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const sessionIdRef = useRef<string | undefined>(undefined);
  const [historyReady, setHistoryReady] = useState(false);

  useEffect(() => {
    // Tab-local history restores server answer IDs; votes are reloaded from Flask.
    try {
      const saved = JSON.parse(sessionStorage.getItem("manufacturing_chat_v1") ?? "null");
      if (saved && typeof saved.sessionId === "string" && Array.isArray(saved.messages)) {
        sessionIdRef.current = saved.sessionId;
        setMessages(saved.messages.filter((m: Message) =>
          m && typeof m.id === "string" && typeof m.content === "string" &&
          (m.role === "user" || m.role === "assistant")).slice(-100));
      }
    } catch { /* Storage may be disabled or an older saved format may be invalid. */ }
    sessionIdRef.current ??= crypto.randomUUID();
    setHistoryReady(true);
  }, []);

  useEffect(() => {
    if (!historyReady) return;
    try {
      sessionStorage.setItem("manufacturing_chat_v1", JSON.stringify({
        sessionId: sessionIdRef.current, messages: messages.slice(-100),
      }));
    } catch { /* A full browser store must not prevent chatting or saving feedback. */ }
  }, [messages, historyReady]);

  const handleSend = useCallback(async (text: string) => {
    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    try {
      // Snapshot history before the new user message (setMessages is async)
      const history = messages.map(({ role, content }) => ({ role, content }));

      sessionIdRef.current ??= crypto.randomUUID();
      const response = await sendMessage(text, history, sessionIdRef.current);

      // Persist session ID for stateful backends
      if (response.session_id) {
        sessionIdRef.current = response.session_id;
      }

      const aiMessage: Message = {
        id: response.message_id ?? crypto.randomUUID(),
        feedbackId: response.message_id,
        feedbackUnavailable: response.feedback_unavailable,
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
          id: crypto.randomUUID(),
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
      sessionIdRef.current ??= crypto.randomUUID();
      const response = await sendMessage(selectedValue, history, sessionIdRef.current);
      if (response.session_id) {
        sessionIdRef.current = response.session_id;
      }
      setMessages((prev) => [
        ...prev,
        {
          id: response.message_id ?? crypto.randomUUID(),
          feedbackId: response.message_id,
          feedbackUnavailable: response.feedback_unavailable,
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
          id: crypto.randomUUID(),
          role: "assistant",
          content: "Sorry, I couldn't reach the assistant. Please check that the backend is running and try again.",
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [messages]);

  // The server resolves the selected answer and saved feedback by ID.
  const handleRewrite = useCallback(async (answerMessage: Message) => {
    if (isLoading || !answerMessage.feedbackId) return;

    setIsLoading(true);
    try {
      const response = await rewriteFeedback(answerMessage.feedbackId);
      setMessages((prev) => [
        ...prev,
        {
          id: response.message_id ?? crypto.randomUUID(),
          feedbackId: response.message_id,
          feedbackUnavailable: response.feedback_unavailable,
          role: "assistant",
          content: response.reply,
          timestamp: new Date().toISOString(),
          sources: response.metadata?.sources,
          clarification: response.metadata?.clarification,
        },
      ]);
    } catch (err) {
      console.error("[chat] rewrite API call failed:", err);
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "Sorry, I couldn't rewrite that answer right now. Please try again.",
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [isLoading]);

  const hasMessages = messages.length > 0 || isLoading;

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <Header onDocsClick={() => setIsSidebarOpen(true)} />

      <DocumentSidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
      />

      {hasMessages ? (
        <ChatPage
          messages={messages}
          onSend={handleSend}
          onClarificationSelect={handleClarificationSelect}
          onRewrite={handleRewrite}
          isLoading={isLoading}
        />
      ) : (
        <WelcomePage onSend={handleSend} />
      )}
    </div>
  );
}
