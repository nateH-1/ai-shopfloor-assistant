"use client";

import { useEffect, useRef, useState, KeyboardEvent } from "react";
import { transcribeAudio } from "@/lib/chatApi";
import { get_verification_status } from "@/lib/authApi";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export default function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const animFrameRef = useRef<number>(0);
  const [verificationStatus, setVerificationStatus] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      cancelAnimationFrame(animFrameRef.current);
      audioCtxRef.current?.close();
    };
  }, []);

  useEffect(() => {
    let active = true;
    async function get_status() {
      try {
        const data = await get_verification_status();
        if (active) {
          setVerificationStatus(data.verification_status);
        }
      } catch (error) {
        if (active) {
          setError(error instanceof Error ? error.message : "Failed to load verification status.");
        }
      }
    }
    void get_status();
    return () => {
      active = false;
    };
  }, []);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled || isTranscribing || isRecording) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  };

  const stopRecorder = () => {
    mediaRecorderRef.current?.stop();
    setIsRecording(false);
  };

  const startVisualizer = (stream: MediaStream) => {
    const audioCtx = new AudioContext();
    audioCtxRef.current = audioCtx;
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256; // 128 frequency bins
    analyserRef.current = analyser;
    audioCtx.createMediaStreamSource(stream).connect(analyser);

    const dataArray = new Uint8Array(analyser.frequencyBinCount);

    const draw = () => {
      animFrameRef.current = requestAnimationFrame(draw);
      const canvas = canvasRef.current;
      if (!canvas || !canvas.offsetWidth) return;

      // Keep canvas resolution in sync with its CSS display size
      if (canvas.width !== canvas.offsetWidth) {
        canvas.width = canvas.offsetWidth;
      }

      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      analyser.getByteFrequencyData(dataArray);

      const W = canvas.width;
      const H = canvas.height;
      ctx.clearRect(0, 0, W, H);

      const barCount = 64;
      const gap = 1;
      const barW = Math.max(1.5, (W - gap * (barCount - 1)) / barCount);
      // Only sample the lower 60 % of bins — speech energy lives there;
      // the top 40 % of high-freq bins are almost always silent.
      const usableBins = Math.floor(dataArray.length * 0.6);

      for (let i = 0; i < barCount; i++) {
        const idx = Math.floor((i / barCount) * usableBins);
        const amplitude = dataArray[idx] / 255;
        const barH = Math.max(3, amplitude * H * 0.85);
        const x = i * (barW + gap);
        const y = (H - barH) / 2;
        const alpha = 0.35 + amplitude * 0.65;
        ctx.fillStyle = `rgba(59,130,246,${alpha.toFixed(2)})`;
        ctx.fillRect(x, y, barW, barH);
      }
    };

    draw();
  };

  const stopVisualizer = () => {
    cancelAnimationFrame(animFrameRef.current);
    analyserRef.current = null;
    audioCtxRef.current?.close();
    audioCtxRef.current = null;

    // Clear the canvas
    const canvas = canvasRef.current;
    if (canvas) {
      const ctx = canvas.getContext("2d");
      ctx?.clearRect(0, 0, canvas.width, canvas.height);
    }
  };

  const startRecorder = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      window.alert("Voice input is not supported in this browser.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      chunksRef.current = [];

      let recorder: MediaRecorder;
      try {
        recorder = new MediaRecorder(stream);
      } catch (recorderErr) {
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        throw recorderErr;
      }
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        stopVisualizer();

        const audioBlob = new Blob(chunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });

        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        mediaRecorderRef.current = null;

        if (audioBlob.size === 0) return;

        setIsTranscribing(true);
        try {
          const text = await transcribeAudio(audioBlob);
          setValue((prev) => (prev ? `${prev} ${text}`.trim() : text));
          requestAnimationFrame(() => handleInput());
        } catch (err) {
          console.error("[voice] transcription failed:", err);
          window.alert(err instanceof Error ? err.message : "Failed to transcribe audio.");
        } finally {
          setIsTranscribing(false);
        }
      };

      recorder.start();
      setIsRecording(true);
      startVisualizer(stream);
    } catch (err) {
      console.error("[voice] microphone access failed:", err);
      window.alert("Microphone access was denied or unavailable.");
    }
  };

  const handleMicClick = async () => {
    if (disabled || isTranscribing) return;
    if (isRecording) {
      stopRecorder();
      return;
    }
    await startRecorder();
  };

  return (
    <div
      className="flex items-center gap-3 bg-white rounded-2xl px-4 py-3"
      style={{
        boxShadow: "0 4px 24px 0 rgba(0,0,0,0.10)",
        border: "1px solid #e5e7eb",
      }}
    >
      { error ? (
        <p role="alert" className="w-full rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-center text-sm font-medium leading-relaxed text-red-700">{error}</p>
      ) : verificationStatus != "VERIFIED" ? (
        <p role="status" className="w-full rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-center text-sm font-medium leading-relaxed text-blue-800">Please wait for an admin to verify your account.</p>
      ) : (
        <>
          {/* Attachment icon */}
        <button
          className="shrink-0 text-gray-400 hover:text-gray-600 transition-colors"
          aria-label="Attach file"
          type="button"
        >
          <PaperclipIcon className="w-5 h-5" />
        </button>

        {/* Text input / Audio visualizer */}
        <div className="flex-1" style={{ minHeight: "24px" }}>
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            onInput={handleInput}
            placeholder={isTranscribing ? "Transcribing audio..." : "Ask Kuldeep about manuals, SOPs, or processes..."}
            disabled={disabled || isTranscribing}
            className="w-full resize-none bg-transparent text-[#374151] placeholder-gray-400 text-sm leading-relaxed focus:outline-none"
            style={{ minHeight: "24px", maxHeight: "160px", display: isRecording ? "none" : undefined }}
          />
          {/* Canvas is always mounted so canvasRef is always set; shown only while recording */}
          <canvas
            ref={canvasRef}
            style={{
              display: isRecording ? "block" : "none",
              width: "100%",
              height: "32px",
            }}
          />
        </div>

        {/* Mic icon */}
        <button
          className={`relative shrink-0 w-10 h-10 rounded-full flex items-center justify-center transition-all duration-200 ${
            isTranscribing
              ? "bg-amber-50 text-amber-600 border border-amber-200"
              : isRecording
                ? "bg-red-50 text-red-600 border border-red-200 shadow-[0_0_0_6px_rgba(239,68,68,0.10)]"
                : "bg-gray-50 text-gray-500 border border-gray-200 hover:bg-gray-100 hover:text-gray-700"
          }`}
          aria-label={isRecording ? "Stop voice recording" : "Start voice recording"}
          title={isTranscribing ? "Transcribing" : isRecording ? "Recording" : "Voice input"}
          type="button"
          onClick={handleMicClick}
          disabled={disabled || isTranscribing}
        >
          {isRecording && (
            <span className="absolute inset-0 rounded-full border-2 border-red-300 animate-ping" />
          )}
          <MicIcon className="w-5 h-5" />
        </button>

        {/* Send button */}
        <button
          onClick={handleSend}
          disabled={!value.trim() || disabled || isTranscribing || isRecording}
          className="shrink-0 flex items-center justify-center w-8 h-8 rounded-full transition-opacity"
          style={{ backgroundColor: "#3B82F6" }}
          aria-label="Send message"
          type="button"
        >
          <SendIcon className="w-4 h-4 text-white" />
        </button>
        </>
      )}
    </div>
  );
}

// ─── Icons ────────────────────────────────────────────────────────────────────

function PaperclipIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
    </svg>
  );
}

function MicIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  );
}

function SendIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
      <path d="M22 2L11 13" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
      <path d="M22 2L15 22L11 13L2 9L22 2Z" fill="white"/>
    </svg>
  );
}
