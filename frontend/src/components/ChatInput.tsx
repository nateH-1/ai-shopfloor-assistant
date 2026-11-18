"use client";

import { useEffect, useLayoutEffect, useRef, useState, type ClipboardEvent, type KeyboardEvent, type MouseEvent } from "react";
import { findMisspellings, transcribeAudio, type SpellSpan } from "@/lib/chatApi";
import { readEditorText, selectionOffsets, setSelectionOffsets, type CaretOffsets } from "@/lib/editorCaret";
import { highlightedHtml } from "@/lib/spellMarkup";
import { replaceMisspelling } from "@/lib/spellcheck";
import { get_verification_status } from "@/lib/authApi";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export default function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const editorRef = useRef<HTMLDivElement>(null);
  const caretRef = useRef<CaretOffsets | null>(null);
  const composingRef = useRef(false);
  const suggestionMenuRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const animFrameRef = useRef<number>(0);
  const [verificationStatus, setVerificationStatus] = useState("");
  const [error, setError] = useState("");
  const [spellSpans, setSpellSpans] = useState<SpellSpan[]>([]);
  const [suggestionMenu, setSuggestionMenu] = useState<{
    x: number;
    y: number;
    start: number;
    end: number;
    suggestions: string[];
  } | null>(null);

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      cancelAnimationFrame(animFrameRef.current);
      audioCtxRef.current?.close();
    };
  }, []);

  useEffect(() => {
    const text = value;
    if (!text.trim()) {
      setSpellSpans([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      findMisspellings(text, controller.signal)
        .then((spans) => {
          if (!controller.signal.aborted) setSpellSpans(spans);
        })
        .catch(() => {
          if (!controller.signal.aborted) setSpellSpans([]);
        });
    }, 300);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [value]);

  useLayoutEffect(() => {
    const root = editorRef.current;
    const saved = caretRef.current;
    if (!root || !saved || composingRef.current || document.activeElement !== root) return;
    const current = selectionOffsets(root);
    if (current && current.start === saved.start && current.end === saved.end) return;
    setSelectionOffsets(root, saved.start, saved.end);
  }, [value, spellSpans]);

  useEffect(() => {
    if (!suggestionMenu) return;
    const close = (event: PointerEvent) => {
      if (suggestionMenuRef.current?.contains(event.target as Node)) return;
      setSuggestionMenu(null);
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setSuggestionMenu(null);
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [suggestionMenu]);

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

  const rememberCaret = () => {
    const root = editorRef.current;
    if (!root) return;
    const offsets = selectionOffsets(root);
    if (offsets) caretRef.current = offsets;
  };

  const insertAtCaret = (extra: string) => {
    const root = editorRef.current;
    if (!root) return;
    const current = readEditorText(root);
    const offsets = selectionOffsets(root) ?? caretRef.current ?? { start: current.length, end: current.length };
    const next = current.slice(0, offsets.start) + extra + current.slice(offsets.end);
    const caret = offsets.start + extra.length;
    caretRef.current = { start: caret, end: caret };
    setValue(next);
  };

  const handleSend = () => {
    const current = editorRef.current ? readEditorText(editorRef.current) : value;
    const trimmed = current.trim();
    if (!trimmed || disabled || isTranscribing || isRecording) return;
    onSend(trimmed);
    caretRef.current = { start: 0, end: 0 };
    setValue("");
    setSpellSpans([]);
  };

  const handleEditorInput = () => {
    const root = editorRef.current;
    if (!root || composingRef.current) return;
    rememberCaret();
    setSuggestionMenu(null);
    setValue(readEditorText(root));
  };

  const applySuggestion = (start: number, end: number, suggestion: string) => {
    const root = editorRef.current;
    const current = root ? readEditorText(root) : value;
    const replaced = replaceMisspelling(current, start, end, suggestion);
    if (!replaced) return;
    const delta = suggestion.length - (end - start);
    caretRef.current = { start: replaced.caret, end: replaced.caret };
    root?.focus();
    setSpellSpans((spans) => spans.flatMap((span) => {
      if (span.start === start && span.end === end) return [];
      if (span.end <= start) return [span];
      if (span.start >= end) return [{ ...span, start: span.start + delta, end: span.end + delta }];
      return [];
    }));
    setSuggestionMenu(null);
    setValue(replaced.text);
  };

  const openSuggestions = (event: MouseEvent<HTMLDivElement>, fromContextMenu: boolean) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const word = target.closest(".misspelled-word");
    if (!word || !editorRef.current?.contains(word)) return;
    if (!fromContextMenu && window.getSelection() && !window.getSelection()?.isCollapsed) return;
    const start = Number(word.getAttribute("data-start"));
    const end = Number(word.getAttribute("data-end"));
    const match = spellSpans.find((span) => span.start === start && span.end === end);
    const suggestions = match?.suggestions?.filter((item) => item.trim()) ?? [];
    if (suggestions.length === 0) return;
    if (fromContextMenu) event.preventDefault();
    const rect = word.getBoundingClientRect();
    setSuggestionMenu({
      x: Math.max(8, Math.min(rect.left, window.innerWidth - 200)),
      y: Math.min(rect.bottom + 4, window.innerHeight - 180),
      start,
      end,
      suggestions,
    });
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (suggestionMenu && e.key === "Escape") {
      e.preventDefault();
      setSuggestionMenu(null);
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
      return;
    }
    if (e.key === "Enter" && e.shiftKey) {
      e.preventDefault();
      insertAtCaret("\n");
    }
  };

  const handlePaste = (e: ClipboardEvent<HTMLDivElement>) => {
    e.preventDefault();
    insertAtCaret(e.clipboardData.getData("text/plain").replace(/\r\n/g, "\n"));
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
          setValue((prev) => {
            const next = prev ? `${prev} ${text}`.trim() : text;
            caretRef.current = { start: next.length, end: next.length };
            return next;
          });
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
      className="flex items-center gap-3 border border-border bg-card rounded-2xl px-4 py-3"
      style={{
        boxShadow: "0 4px 24px 0 rgba(0,0,0,0.10)",
      }}
    >
      { error ? (
        <p role="alert" className="w-full rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-center text-sm font-medium leading-relaxed text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">{error}</p>
      ) : verificationStatus != "VERIFIED" ? (
        <p role="status" className="w-full rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-center text-sm font-medium leading-relaxed text-blue-800 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-300">Please wait for an admin to verify your account.</p>
      ) : (
        <>

        {/* Text input / Audio visualizer */}
        <div className="min-w-0 flex-1">
          <div
            ref={editorRef}
            role="textbox"
            aria-multiline="true"
            aria-disabled={disabled || isTranscribing || undefined}
            aria-describedby={spellSpans.length > 0 ? "draft-spelling" : undefined}
            data-placeholder={isTranscribing ? "Transcribing audio..." : "Ask Kuldeep about manuals, SOPs, or processes..."}
            contentEditable={!disabled && !isTranscribing}
            spellCheck={false}
            suppressContentEditableWarning
            onInput={handleEditorInput}
            onKeyDown={handleKeyDown}
            onKeyUp={rememberCaret}
            onMouseUp={rememberCaret}
            onPaste={handlePaste}
            onClick={(event) => openSuggestions(event, false)}
            onContextMenu={(event) => openSuggestions(event, true)}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={() => {
              composingRef.current = false;
              handleEditorInput();
            }}
            dangerouslySetInnerHTML={{ __html: highlightedHtml(value, spellSpans) }}
            className={`spell-editor wrap-break-word text-sm leading-relaxed text-foreground focus:outline-none ${isRecording ? "hidden" : ""}`}
          />
          {suggestionMenu && (
            <div
              ref={suggestionMenuRef}
              role="menu"
              aria-label="Spelling suggestions"
              className="fixed z-50 min-w-36 rounded-xl border border-border bg-card py-1 text-sm text-foreground shadow-lg"
              style={{ left: suggestionMenu.x, top: suggestionMenu.y }}
              onPointerDown={(event) => event.stopPropagation()}
            >
              {suggestionMenu.suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  role="menuitem"
                  className="block w-full px-3 py-1.5 text-left hover:bg-muted"
                  onPointerDown={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    applySuggestion(suggestionMenu.start, suggestionMenu.end, suggestion);
                  }}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          )}
          {spellSpans.length > 0 && (
            <span id="draft-spelling" className="sr-only" role="status">
              Some words are underlined because they are misspelled or not real words.
            </span>
          )}
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
              ? "bg-amber-50 text-amber-600 border border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900"
              : isRecording
                ? "bg-red-50 text-red-600 border border-red-200 shadow-[0_0_0_6px_rgba(239,68,68,0.10)] dark:bg-red-950 dark:text-red-300 dark:border-red-900"
                : "bg-card text-muted-foreground border border-border hover:bg-muted hover:text-foreground"
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
          className="shrink-0 flex items-center justify-center w-8 h-8 rounded-full bg-blue-button-solid text-blue-button-solid-text transition-opacity"
          aria-label="Send message"
          type="button"
        >
          <SendIcon className="w-4 h-4" />
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
