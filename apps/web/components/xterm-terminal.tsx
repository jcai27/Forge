"use client";

import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

export function XtermTerminal({
  sessionId,
}: {
  sessionId: string;
}) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!terminalRef.current) return;

    const term = new Terminal({
      theme: {
        background: "#070912",
        foreground: "#d5d9e6",
        cursor: "#8b96ff",
        cursorAccent: "#070912",
        selectionBackground: "rgba(139, 150, 255, 0.18)",
        black: "#070912",
        brightBlack: "#606a80",
        green: "#4ade80",
        red: "#fb7185",
        yellow: "#fbbf24",
        blue: "#7c8cff",
        magenta: "#e879f9",
        cyan: "#67e8f9",
      },
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
      fontSize: 13,
      cursorBlink: true,
    });
    
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalRef.current);
    fitAddon.fit();
    xtermRef.current = term;

    // Connect to WebSocket
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    // We assume apiOrigin is handled by a proxy or we can use the same origin if running together
    // For local dev, API is usually on 8000
    const apiOrigin = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const wsUrl = apiOrigin.replace(/^http/, "ws") + `/candidate/sessions/${sessionId}/pty?dev_auth_as=candidate`;
    
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      term.writeln("\x1b[32mConnected to interactive terminal.\x1b[0m");
    };

    ws.onmessage = (event) => {
      term.write(event.data);
    };

    ws.onclose = () => {
      term.writeln("\r\n\x1b[31mDisconnected from terminal.\x1b[0m");
    };

    ws.onerror = (error) => {
      term.writeln("\r\n\x1b[31mWebSocket Error.\x1b[0m");
    };

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(data);
      }
    });

    const handleResize = () => {
      fitAddon.fit();
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      ws.close();
      term.dispose();
    };
  }, [sessionId]);

    return <div ref={terminalRef} className="h-full w-full overflow-hidden rounded-[18px] border border-indigo-400/12 bg-[#070912] p-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]" />;
  }
