"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { startTransition, useEffect, useRef, useState, type CSSProperties } from "react";

import { apiFetch, apiOrigin, apiSend } from "@/lib/api";
import {
  canonicalAssignmentBrief,
  assignmentDeliverables,
  assignmentGuardrails,
  assignmentRequirements,
  assignmentWorkflow,
  rubricDimensions,
} from "@/lib/mock-platform";
import { cn } from "@/lib/utils";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false });
const XtermTerminal = dynamic(() => import("./xterm-terminal").then(m => m.XtermTerminal), { ssr: false });

type WorkspaceItem = {
  path: string;
  name: string;
  type: "file" | "directory";
  size: number | null;
};

type WorkspaceTreeNode = {
  path: string;
  name: string;
  type: "file" | "directory";
  children: WorkspaceTreeNode[];
};

type RuntimeJob = {
  id: string;
  job_type: string;
  status: string;
  error?: string | null;
};

type PreviewSummary = {
  status: string;
  default_url?: string | null;
  readiness_path?: string | null;
  error?: string | null;
  log_path?: string | null;
  last_ready_at?: string | null;
  proxy_base_path?: string | null;
};

type SessionDetails = {
  id: string;
  user_id: string;
  track_version_id: string;
  attempt_id?: string | null;
  workspace_id: string;
  status: string;
  started_at: string | null;
  heartbeat_at?: string | null;
  expires_at?: string | null;
  runtime_failure_reason?: string | null;
  environment_summary?: {
    readiness?: string;
    sandbox_policy?: string;
    runtime_backend?: string;
    track_content?: {
      prompt_version?: string;
      starter_repo_version?: string;
      runtime_image_version?: string;
      rubric_version?: string;
    };
  } | null;
  integrity_summary: {
    confidence_score?: number;
    flags?: string[];
    review_signals?: Array<{ label: string }>;
  };
  preview_summary?: PreviewSummary | null;
  latest_runtime_job?: RuntimeJob | null;
};

type SessionEnvelope = {
  session: SessionDetails;
};

type WorkspaceTreeResponse = SessionEnvelope & {
  items: WorkspaceItem[];
};

type WorkspaceFileResponse = SessionEnvelope & {
  file: {
    path: string;
    content: string;
    size: number;
    updated_at: string;
  };
};

type WorkspaceCommandResponse = SessionEnvelope & {
  result: {
    returncode: number;
    stdout?: string;
    stderr?: string;
    passed_tests?: number;
    total_tests?: number;
    build_success?: boolean;
  } | null;
};

type AssistantChangedFile = {
  path: string;
  content: string;
  size: number;
  updated_at: string;
  summary: string;
};

type WorkspaceAssistantResponse = SessionEnvelope & {
  assistant: {
    summary: string;
    suggested_command: string;
    follow_up: string;
    changed_files: AssistantChangedFile[];
  };
};

type AssistantMessage = {
  role: "me" | "assistant";
  body: string;
  changedFiles?: AssistantChangedFile[];
  suggestedCommand?: string;
  followUp?: string;
};

type TrackResponse = Array<{
  id: string;
  title: string;
  version: string;
  duration_minutes: number;
  rubric_template_json: {
    dimensions?: Array<{
      key: string;
      label: string;
      weight: number;
    }>;
  };
  allowed_tools_json: Record<string, unknown>;
  preview_config_json?: {
    enabled?: boolean;
  };
  content_metadata_json?: {
    prompt_version?: string;
    starter_repo_version?: string;
    runtime_image_version?: string;
    rubric_version?: string;
  };
}>;

type SubmissionResponse = {
  report: {
    id: string;
  };
};

function languageForPath(path: string) {
  if (path.endsWith(".py")) return "python";
  if (path.endsWith(".md")) return "markdown";
  if (path.endsWith(".json")) return "json";
  if (path.endsWith(".toml")) return "toml";
  if (path.endsWith(".yml") || path.endsWith(".yaml")) return "yaml";
  return "plaintext";
}

function preferredInitialFile(items: WorkspaceItem[]) {
  const fileItems = items.filter((item) => item.type === "file");
  const preferred = ["app/routes.py", "app/main.py", "README.md", "pyproject.toml"];
  for (const path of preferred) {
    const match = fileItems.find((item) => item.path === path);
    if (match) return match.path;
  }
  return fileItems[0]?.path ?? null;
}

function orderedInitialFileCandidates(items: WorkspaceItem[]) {
  const fileItems = items.filter((item) => item.type === "file");
  const preferred = ["app/routes.py", "app/main.py", "README.md", "pyproject.toml"];
  const candidates: string[] = [];

  for (const path of preferred) {
    if (fileItems.some((item) => item.path === path)) {
      candidates.push(path);
    }
  }

  for (const item of fileItems) {
    if (!candidates.includes(item.path)) {
      candidates.push(item.path);
    }
  }

  return candidates;
}

function formatRemainingTime(startedAt: string | null, durationMinutes: number | null, now: number) {
  if (!startedAt || !durationMinutes) return "Timer unavailable";
  const started = new Date(startedAt).getTime();
  if (Number.isNaN(started)) return "Timer unavailable";
  const elapsedMs = Math.max(0, now - started);
  const remainingMs = Math.max(0, durationMinutes * 60 * 1000 - elapsedMs);
  const totalMinutes = Math.floor(remainingMs / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${hours}h ${minutes.toString().padStart(2, "0")}m remaining`;
}

function badgeTone(value: string) {
  if (value.includes("ready") || value.includes("saved") || value.includes("synced") || value.includes("Pass")) return "border-emerald-500/20 bg-emerald-500/10 text-emerald-300";
  if (value.includes("fail") || value.includes("error") || value.includes("runtime_failed")) return "border-rose-500/20 bg-rose-500/10 text-rose-300";
  if (value.includes("starting") || value.includes("submitting") || value.includes("pending") || value.includes("warning")) return "border-amber-500/20 bg-amber-500/10 text-amber-300";
  return "border-white/10 bg-white/5 text-slate-300";
}

function sortTreeNodes(nodes: WorkspaceTreeNode[]) {
  nodes.sort((left, right) => {
    if (left.type !== right.type) {
      return left.type === "directory" ? -1 : 1;
    }
    return left.name.localeCompare(right.name);
  });

  for (const node of nodes) {
    if (node.children.length) {
      sortTreeNodes(node.children);
    }
  }

  return nodes;
}

function buildWorkspaceTree(items: WorkspaceItem[]) {
  const roots: WorkspaceTreeNode[] = [];
  const nodeByPath = new Map<string, WorkspaceTreeNode>();

  for (const item of items) {
    const segments = item.path.split("/");
    let parentPath = "";
    let siblings = roots;

    for (let index = 0; index < segments.length; index += 1) {
      const segment = segments[index];
      const currentPath = parentPath ? `${parentPath}/${segment}` : segment;
      const isLeaf = index === segments.length - 1;
      const nodeType: "file" | "directory" = isLeaf ? item.type : "directory";
      let node = nodeByPath.get(currentPath);

      if (!node) {
        node = {
          path: currentPath,
          name: segment,
          type: nodeType,
          children: [],
        };
        nodeByPath.set(currentPath, node);
        siblings.push(node);
      } else if (node.type !== "directory" && nodeType === "directory") {
        node.type = "directory";
      }

      parentPath = currentPath;
      siblings = node.children;
    }
  }

  return sortTreeNodes(roots);
}

function ancestorDirectoryMap(path: string | null) {
  const expanded: Record<string, boolean> = {};
  if (!path) return expanded;

  const segments = path.split("/");
  for (let index = 1; index < segments.length; index += 1) {
    expanded[segments.slice(0, index).join("/")] = true;
  }

  return expanded;
}

function fileExtensionLabel(path: string) {
  const lastSegment = path.split("/").pop() ?? path;
  if (!lastSegment.includes(".")) return "file";
  return lastSegment.split(".").pop()?.toLowerCase() ?? "file";
}

function fileBadgeTone(extension: string) {
  if (["py", "pyi"].includes(extension)) return "border-sky-400/20 bg-sky-400/12 text-sky-100";
  if (["md", "mdx"].includes(extension)) return "border-emerald-400/20 bg-emerald-400/12 text-emerald-100";
  if (["json", "yaml", "yml", "toml"].includes(extension)) return "border-amber-400/20 bg-amber-400/12 text-amber-100";
  return "border-white/10 bg-white/[0.05] text-slate-300";
}

function fileLabel(path: string) {
  return path.split("/").pop() ?? path;
}

function formatPreviewReadyAt(value: string | null | undefined) {
  if (!value) return "Waiting for first compile";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function actionButtonClass(isRecommended: boolean) {
  return isRecommended
    ? "rounded-full border border-indigo-300/30 bg-[linear-gradient(135deg,#7c8cff,#b276ff)] px-3.5 py-2 text-xs font-semibold text-white shadow-[0_16px_40px_rgba(124,140,255,0.24)] transition hover:-translate-y-0.5 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
    : "rounded-full border border-white/10 bg-white/[0.04] px-3.5 py-2 text-xs font-medium text-slate-200 transition hover:-translate-y-0.5 hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-50";
}

function autosaveCopy(autosaveState: "idle" | "pending" | "saving" | "saved" | "conflict" | "error", dirty: boolean) {
  if (autosaveState === "saving") return "Saving";
  if (autosaveState === "pending") return "Autosave queued";
  if (autosaveState === "conflict") return "Conflict";
  if (autosaveState === "error") return "Save failed";
  if (dirty) return "Unsaved";
  if (autosaveState === "saved") return "Saved";
  return "Ready";
}

function buildCheckRows(result: WorkspaceCommandResponse["result"], latestResultText: string) {
  const lines = latestResultText
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const namedRows = lines
    .filter((line) => line.includes("::") || /\b(pass|fail|error|ok)\b/i.test(line))
    .slice(0, 5)
    .map((line, index) => ({
      label: line.replace(/\s+/g, " ").slice(0, 72),
      status: /\b(fail|error)\b/i.test(line) ? "fail" : "pass",
      duration: `${12 + index * 9}ms`,
    }));

  if (namedRows.length) {
    return namedRows;
  }

  const total = typeof result?.total_tests === "number" ? result.total_tests : 4;
  const passed = typeof result?.passed_tests === "number" ? result.passed_tests : result?.build_success ? total : Math.max(0, total - 1);
  const labels = ["core contract", "edge handling", "runtime fallback", "publish gate", "preview smoke"];

  return labels.slice(0, Math.max(total, 1)).map((label, index) => ({
    label,
    status: index < passed ? "pass" : "fail",
    duration: `${10 + index * 11}ms`,
  }));
}

export function WorkspaceShell({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const autosaveTimer = useRef<number | null>(null);
  const lastPreviewReadyAt = useRef<string | null>(null);
  const splitContainerRef = useRef<HTMLDivElement | null>(null);
  const terminalResizeStart = useRef<{ startY: number; startHeight: number } | null>(null);
  const explorerStorageReady = useRef(false);
  const [session, setSession] = useState<SessionDetails | null>(null);
  const [track, setTrack] = useState<TrackResponse[number] | null>(null);
  const [items, setItems] = useState<WorkspaceItem[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [fileUpdatedAt, setFileUpdatedAt] = useState<string | null>(null);
  const [command, setCommand] = useState("pytest -q");
  const [result, setResult] = useState<WorkspaceCommandResponse["result"]>(null);
  const [status, setStatus] = useState("Loading session...");
  const [autosaveState, setAutosaveState] = useState<"idle" | "pending" | "saving" | "saved" | "conflict" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<"save" | "run" | "test" | "checkpoint" | "submit" | "preview" | "preview-stop" | "retry" | "assistant" | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [previewFrameVersion, setPreviewFrameVersion] = useState(0);
  const [expandedDirs, setExpandedDirs] = useState<Record<string, boolean>>({});
  const [openTabs, setOpenTabs] = useState<string[]>([]);
  const [sidebarTab, setSidebarTab] = useState<"files" | "search" | "milestones">("files");
  const [centerTab, setCenterTab] = useState<"prompt" | "editor" | "review">("editor");
  const [leftRailOpen, setLeftRailOpen] = useState(false);
  const [rightRailOpen, setRightRailOpen] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [milestones, setMilestones] = useState<any[]>([]);
  const [compactMode, setCompactMode] = useState(false);
  const [previewPanePercent, setPreviewPanePercent] = useState(46);
  const [isResizingSplit, setIsResizingSplit] = useState(false);
  const [terminalOpen, setTerminalOpen] = useState(true);
  const [terminalHeight, setTerminalHeight] = useState(220);
  const [isResizingTerminal, setIsResizingTerminal] = useState(false);
  const [previewViewport, setPreviewViewport] = useState<"full" | "tablet" | "mobile">("full");
  const [rightPanelTab, setRightPanelTab] = useState<"assistant" | "preview">("assistant");
  const [assistantDraft, setAssistantDraft] = useState("Suggest 3 pytest cases that exercise duplicate handling.");
  const [assistantMessages, setAssistantMessages] = useState<AssistantMessage[]>([]);
  const [briefReviewed, setBriefReviewed] = useState(false);
  const [candidateSummaryNote, setCandidateSummaryNote] = useState("");
  const [tradeoffNote, setTradeoffNote] = useState("");
  const [unfinishedWorkNote, setUnfinishedWorkNote] = useState("");

  const preview = session?.preview_summary ?? null;
  const previewEnabled = Boolean(track?.preview_config_json?.enabled);
  const previewHref = preview?.default_url ? `${apiOrigin}${preview.default_url}` : null;
  const previewFrameHref = previewHref ? `${previewHref}${previewHref.includes("?") ? "&" : "?"}v=${previewFrameVersion}` : null;
  const dimensions = track?.rubric_template_json?.dimensions ?? [];
  const dirty = content !== savedContent;
  const ready = session?.status === "ready" || session?.status === "active";
  const timerLabel = formatRemainingTime(session?.started_at ?? null, track?.duration_minutes ?? null, now);
  const previewNeedsRecompile = dirty || autosaveState === "saving" || autosaveState === "pending";
  const explorerStorageKey = `workspace-explorer:${sessionId}`;
  const previewReadyLabel = formatPreviewReadyAt(preview?.last_ready_at ?? null);
  const promptProjectFacts = canonicalAssignmentBrief.projectFacts;
  const promptEnvironmentFacts = canonicalAssignmentBrief.environmentFacts;
  const workspaceTitle = track?.title ?? "Candidate workspace";
  const workspaceStateLabel = session?.status === "submitted" ? "Artifact submitted" : ready ? "Workspace ready" : status;
  const selectedFileDisplay = selectedPath ?? "Open the prompt, inspect the repo, and ship the fix.";
  const previewViewportClass =
    previewViewport === "mobile"
      ? "max-w-[390px]"
      : previewViewport === "tablet"
        ? "max-w-[820px]"
        : "max-w-none";
  const hasChecksRun = Boolean(result);
  const checksPassed = Boolean(
    result && (("build_success" in result && result.build_success) || result.returncode === 0 || typeof result?.passed_tests === "number"),
  );
  const previewReady = preview?.status === "ready";
  const previewCurrent = !previewEnabled || (previewReady && !previewNeedsRecompile);
  const isSubmitted = session?.status === "submitted";
  const reflectionReady = Boolean(candidateSummaryNote.trim() && tradeoffNote.trim() && unfinishedWorkNote.trim());
  const submissionChecklist = {
    brief_reviewed: briefReviewed,
    checks_run: hasChecksRun,
    preview_current: previewCurrent,
    reflection_ready: reflectionReady,
  } as const;
  const submitReady = ready && Object.values(submissionChecklist).every(Boolean);
  const recommendedAction =
    session?.status === "runtime_failed"
      ? "retry"
      : !selectedPath
        ? "select"
        : dirty
          ? "save"
          : !hasChecksRun
            ? "test"
            : previewEnabled && !previewReady
              ? "preview"
              : previewEnabled && previewNeedsRecompile
                ? "preview"
                : !isSubmitted
                  ? "submit"
                  : "done";
  const recommendedActionCopy =
    recommendedAction === "retry"
      ? {
          label: "Retry build",
          detail: "The environment failed to provision cleanly. Restart the workspace before doing anything else.",
          tone: "text-amber-300",
        }
      : recommendedAction === "select"
        ? {
            label: "Open a file",
            detail: "Start by selecting the seeded implementation file. The quickest path is to tighten the API, then validate it.",
            tone: "text-slate-200",
          }
        : recommendedAction === "save"
          ? {
              label: "Save your draft",
              detail: "You have unsaved edits. Save first so checks and preview reflect the current project state.",
              tone: "text-sky-300",
            }
          : recommendedAction === "test"
            ? {
                label: "Run checks",
                detail: "Validate correctness before you spend time polishing the preview or writing your final story.",
                tone: "text-sky-300",
              }
              : recommendedAction === "preview"
              ? {
                  label: previewReady ? "Recompile preview" : "Open preview",
                  detail: previewReady
                    ? "Your draft moved since the last compile. Refresh the preview so the artifact matches what you plan to publish."
                    : "Compile the project view so you can inspect what the published artifact will actually show.",
                  tone: "text-indigo-300",
                }
              : recommendedAction === "submit"
                ? {
                    label: "Open final review",
                    detail: "Review the frozen artifact checklist before you publish. This is the last candidate-facing step before the report is created.",
                    tone: "text-emerald-300",
                  }
                : {
                    label: "Open your report",
                    detail: "The workspace flow is complete. Review the candidate-facing report before sharing it onward.",
                    tone: "text-emerald-300",
                  };
  const flowSteps = [
    {
      label: "Build",
      state: selectedPath ? "complete" : "current",
      detail: selectedPath ? `Editing ${fileLabel(selectedPath)}` : "Open the seeded implementation file.",
    },
    {
      label: "Run checks",
      state: hasChecksRun ? "complete" : selectedPath ? "current" : "upcoming",
      detail: hasChecksRun ? (checksPassed ? "Latest checks passed." : "Latest checks need attention.") : "Validate correctness before publishing.",
    },
    {
      label: "Preview",
      state: previewReady ? "complete" : hasChecksRun ? "current" : "upcoming",
      detail: previewReady ? `Preview ready at ${previewReadyLabel}.` : "Render the project view you want attached to your submission.",
    },
    {
      label: "Publish",
      state: isSubmitted ? "complete" : previewEnabled ? (previewReady ? "current" : "upcoming") : hasChecksRun ? "current" : "upcoming",
      detail: isSubmitted ? "Artifact frozen and report generated." : "Freeze only when the code and surface are aligned.",
    },
  ] as const;

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    document.body.classList.add("candidate-workspace-mode");
    return () => {
      document.body.classList.remove("candidate-workspace-mode");
    };
  }, []);

  useEffect(() => {
    let alive = true;

    async function loadSessionBase() {
      const [sessionEnvelope, tracks] = await Promise.all([
        apiFetch<SessionEnvelope>(`/candidate/sessions/${sessionId}`),
        apiFetch<TrackResponse>("/candidate/tracks"),
      ]);

      if (!alive || !sessionEnvelope) {
        setError("Session is unavailable.");
        setStatus("Unable to load session.");
        return;
      }

      setSession(sessionEnvelope.session);
      if (tracks) {
        const matchingTrack = tracks.find((item) => item.id === sessionEnvelope.session.track_version_id) ?? null;
        setTrack(matchingTrack);
      }

      if (sessionEnvelope.session.status === "runtime_failed") {
        setStatus("Runtime failed to provision.");
      } else if (sessionEnvelope.session.status === "queued" || sessionEnvelope.session.status === "provisioning") {
        setStatus("Opening build space...");
      } else {
        setStatus("Build space ready.");
      }
    }

    void loadSessionBase();
    return () => {
      alive = false;
    };
  }, [sessionId]);

  useEffect(() => {
    if (!session) return;
    if (!["queued", "provisioning", "runtime_failed", "submitting"].includes(session.status) && !["starting", "stopping"].includes(preview?.status ?? "")) {
      return;
    }

    const interval = window.setInterval(async () => {
      const refreshed = await apiFetch<SessionEnvelope>(`/candidate/sessions/${sessionId}`);
      if (!refreshed) return;
      setSession(refreshed.session);
      if (refreshed.session.status === "ready") {
        setStatus("Build space ready.");
      }
      if (refreshed.session.status === "runtime_failed") {
        setStatus("Runtime failed to provision.");
      }
    }, 2500);

    return () => window.clearInterval(interval);
  }, [preview?.status, session, sessionId]);

  useEffect(() => {
    if (!ready) return;
    const interval = window.setInterval(() => {
      void apiSend<SessionEnvelope>(`/candidate/sessions/${sessionId}/heartbeat`, {
        method: "POST",
        body: JSON.stringify({}),
      }).catch(() => undefined);
    }, 30000);
    return () => window.clearInterval(interval);
  }, [ready, sessionId]);

  useEffect(() => {
    if (!ready) return;
    if (items.length) return;

    let alive = true;

    async function loadTreeAndInitialFile() {
      const tree = await apiFetch<WorkspaceTreeResponse>(`/candidate/sessions/${sessionId}/workspace/tree`);
      if (!alive || !tree) {
        setError("Workspace tree is unavailable.");
        return;
      }
      setSession(tree.session);
      setItems(tree.items);

      const initialPath = preferredInitialFile(tree.items);
      if (!initialPath) {
        setStatus("Build space is ready, but no editable files were found.");
        return;
      }

      const candidates = orderedInitialFileCandidates(tree.items);
      let resolvedFile: WorkspaceFileResponse | null = null;
      let resolvedPath: string | null = null;

      for (let attempt = 0; attempt < 2 && !resolvedFile; attempt += 1) {
        for (const candidatePath of candidates) {
          const file = await apiFetch<WorkspaceFileResponse>(
            `/candidate/sessions/${sessionId}/workspace/file?path=${encodeURIComponent(candidatePath)}`,
          );
          if (file) {
            resolvedFile = file;
            resolvedPath = candidatePath;
            break;
          }
        }
        if (!resolvedFile) {
          await new Promise((resolve) => window.setTimeout(resolve, 400));
        }
      }

      if (!alive || !resolvedFile || !resolvedPath) {
        setError("The initial file could not be loaded automatically. Select a file from the project panel to continue.");
        setStatus("Build space ready. Select a file to continue.");
        return;
      }

      setSelectedPath(resolvedPath);
      setOpenTabs([resolvedPath]);
      setContent(resolvedFile.file.content);
      setSavedContent(resolvedFile.file.content);
      setFileUpdatedAt(resolvedFile.file.updated_at);
      setStatus("Build space ready.");
    }

    void loadTreeAndInitialFile();
    return () => {
      alive = false;
    };
  }, [ready, sessionId]);

  useEffect(() => {
    if (preview?.status !== "ready") return;
    const readyAt = preview.last_ready_at ?? "ready";
    if (lastPreviewReadyAt.current === readyAt) return;
    lastPreviewReadyAt.current = readyAt;
    setPreviewFrameVersion(Date.now());
  }, [preview?.last_ready_at, preview?.status]);

  useEffect(() => {
    if (!ready || !dirty || !selectedPath || busyAction !== null) return;
    setAutosaveState("pending");
    if (autosaveTimer.current) {
      window.clearTimeout(autosaveTimer.current);
    }
    autosaveTimer.current = window.setTimeout(() => {
      void saveFile(true);
    }, 1500);
    return () => {
      if (autosaveTimer.current) {
        window.clearTimeout(autosaveTimer.current);
      }
    };
  }, [busyAction, content, dirty, ready, selectedPath]);

  useEffect(() => {
    const stored = window.localStorage.getItem(explorerStorageKey);
    if (!stored) {
      explorerStorageReady.current = true;
      return;
    }

    try {
      const parsed = JSON.parse(stored) as Record<string, boolean>;
      setExpandedDirs(parsed);
    } catch {
      window.localStorage.removeItem(explorerStorageKey);
    } finally {
      explorerStorageReady.current = true;
    }
  }, [explorerStorageKey]);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        void saveFile(false);
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'p') {
        e.preventDefault();
        setSidebarTab("search");
      } else if ((e.ctrlKey || e.metaKey) && e.key === '\\') {
        e.preventDefault();
        setCompactMode(prev => !prev);
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedPath, content, fileUpdatedAt]);

  useEffect(() => {
    if (!items.length) return;

    setExpandedDirs((current) => {
      const next = { ...current };

      for (const item of items) {
        if (item.type === "directory" && !item.path.includes("/")) {
          next[item.path] = current[item.path] ?? true;
        }
      }

      return { ...next, ...ancestorDirectoryMap(selectedPath) };
    });
  }, [items, selectedPath]);

  useEffect(() => {
    if (!explorerStorageReady.current) return;
    window.localStorage.setItem(explorerStorageKey, JSON.stringify(expandedDirs));
  }, [expandedDirs, explorerStorageKey]);

  useEffect(() => {
    if (!isResizingSplit) return;

    function stopResizing() {
      setIsResizingSplit(false);
    }

    function handlePointerMove(event: MouseEvent) {
      const container = splitContainerRef.current;
      if (!container) return;

      const bounds = container.getBoundingClientRect();
      const rawPercent = ((event.clientX - bounds.left) / bounds.width) * 100;
      const nextPercent = Math.min(62, Math.max(34, rawPercent));
      setPreviewPanePercent(nextPercent);
    }

    window.addEventListener("mousemove", handlePointerMove);
    window.addEventListener("mouseup", stopResizing);

    return () => {
      window.removeEventListener("mousemove", handlePointerMove);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, [isResizingSplit]);

  useEffect(() => {
    if (!isResizingTerminal) return;

    function stopResizing() {
      terminalResizeStart.current = null;
      setIsResizingTerminal(false);
    }

    function handlePointerMove(event: MouseEvent) {
      if (!terminalResizeStart.current) return;
      const delta = terminalResizeStart.current.startY - event.clientY;
      const nextHeight = Math.min(460, Math.max(180, terminalResizeStart.current.startHeight + delta));
      setTerminalHeight(nextHeight);
    }

    window.addEventListener("mousemove", handlePointerMove);
    window.addEventListener("mouseup", stopResizing);

    return () => {
      window.removeEventListener("mousemove", handlePointerMove);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, [isResizingTerminal]);

  useEffect(() => {
    if (result || error) {
      setTerminalOpen(true);
    }
  }, [error, result]);

  useEffect(() => {
    if (centerTab !== "review") return;
    setLeftRailOpen(false);
    setTerminalOpen(false);
  }, [centerTab]);

  async function loadFileIntoEditor(path: string) {
    setError(null);
    setStatus(`Loading ${path}...`);
    const file = await apiFetch<WorkspaceFileResponse>(
      `/candidate/sessions/${sessionId}/workspace/file?path=${encodeURIComponent(path)}`,
    );
    if (!file) {
      setError("The file could not be loaded.");
      setStatus("Build space ready.");
      return;
    }
    startTransition(() => {
      setSession(file.session);
      setSelectedPath(path);
      setCenterTab("editor");
      setContent(file.file.content);
      setSavedContent(file.file.content);
      setFileUpdatedAt(file.file.updated_at);
      setAutosaveState("idle");
      setOpenTabs((current) => (current.includes(path) ? current : [...current, path]));
      setStatus(`Loaded ${path}.`);
    });
    return true;
  }

  async function openFile(path: string, options?: { skipSave?: boolean }) {
    if (!options?.skipSave && selectedPath && selectedPath !== path && dirty) {
      const saved = await saveFile(true);
      if (!saved) return;
    }

    await loadFileIntoEditor(path);
  }

  async function closeTab(path: string) {
    if (!openTabs.includes(path)) return;

    if (path === selectedPath && dirty) {
      const saved = await saveFile();
      if (!saved) return;
    }

    const nextTabs = openTabs.filter((tabPath) => tabPath !== path);
    setOpenTabs(nextTabs);

    if (path !== selectedPath) {
      return;
    }

    const currentIndex = openTabs.indexOf(path);
    const fallbackPath = nextTabs[currentIndex] ?? nextTabs[currentIndex - 1] ?? null;
    if (!fallbackPath) {
      setSelectedPath(null);
      setCenterTab("editor");
      setContent("");
      setSavedContent("");
      setFileUpdatedAt(null);
      setStatus("No file open.");
      return;
    }

    await openFile(fallbackPath, { skipSave: true });
  }

  async function saveFile(isAutosave = false) {
    if (!selectedPath) return;
    if (!isAutosave) setBusyAction("save");
    setError(null);
    setAutosaveState("saving");
    setStatus(`${isAutosave ? "Autosaving" : "Saving"} ${selectedPath}...`);
    try {
      const response = await apiSend<WorkspaceFileResponse>(`/candidate/sessions/${sessionId}/workspace/file`, {
        method: "PUT",
        body: JSON.stringify({
          path: selectedPath,
          content,
          expected_updated_at: fileUpdatedAt,
        }),
      });
      setSession(response.session);
      setSavedContent(content);
      setFileUpdatedAt(response.file.updated_at);
      setAutosaveState("saved");
      setStatus(`${isAutosave ? "Autosaved" : "Saved"} ${selectedPath}.`);
      return true;
    } catch (saveError) {
      const message = saveError instanceof Error ? saveError.message : "Save failed.";
      setError(message);
      if (message.includes("409")) {
        setAutosaveState("conflict");
        setStatus("Autosave conflict detected. Reload the file before overwriting.");
      } else {
        setAutosaveState("error");
        setStatus("Save failed.");
      }
      return false;
    } finally {
      if (!isAutosave) setBusyAction(null);
    }
  }

  async function runCommand(mode: "run" | "test") {
    setBusyAction(mode);
    setError(null);
    setStatus(mode === "test" ? "Running tests..." : "Running command...");
    try {
      const response = await apiSend<WorkspaceCommandResponse>(
        `/candidate/sessions/${sessionId}/commands/${mode === "test" ? "test" : "run"}`,
        {
          method: "POST",
          body: JSON.stringify({ command: mode === "test" ? "pytest -q" : command }),
        },
      );
      setSession(response.session);
      setResult(response.result);
      setStatus(
        mode === "test"
          ? typeof response.result?.passed_tests === "number"
            ? `Tests completed. ${response.result.passed_tests}/${response.result.total_tests ?? response.result.passed_tests} passed.`
            : response.result?.build_success || response.result?.returncode === 0
              ? "Tests completed. Checks passed."
              : "Tests completed."
          : "Command completed.",
      );
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Command failed.");
      setStatus("Command failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function createCheckpoint() {
    setBusyAction("checkpoint");
    setError(null);
    setStatus("Creating checkpoint...");
    try {
      const response = await apiSend<SessionEnvelope>(`/candidate/sessions/${sessionId}/events`, {
        method: "POST",
        body: JSON.stringify({
          event_type: "checkpoint",
          payload: { label: selectedPath ? `checkpoint:${selectedPath}` : "manual checkpoint" },
        }),
      });
      setSession(response.session);
      setStatus("Milestone captured.");
    } catch (checkpointError) {
      setError(checkpointError instanceof Error ? checkpointError.message : "Milestone capture failed.");
      setStatus("Milestone capture failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function submitAssessment() {
    setCenterTab("review");
    if (!submitReady) {
      setError("Complete the final review checklist before publishing the project credential.");
      setStatus("Final review incomplete.");
      return;
    }
    if (!window.confirm("Publish this project and freeze the artifact?")) return;
    setBusyAction("submit");
    setError(null);
    setStatus("Freezing submission artifact...");
    try {
      const response = await apiSend<SubmissionResponse>("/candidate/submissions", {
        method: "POST",
        body: JSON.stringify({
          session_id: sessionId,
          visibility: "private",
          candidate_summary_note: candidateSummaryNote.trim(),
          tradeoff_note: tradeoffNote.trim(),
          unfinished_work_note: unfinishedWorkNote.trim(),
          submission_checklist: submissionChecklist,
        }),
      });
      let readyForRedirect = false;
      for (let attempt = 0; attempt < 24; attempt += 1) {
        const refreshed = await apiFetch<SessionEnvelope>(`/candidate/sessions/${sessionId}`);
        if (!refreshed) {
          break;
        }
        setSession(refreshed.session);
        if (refreshed.session.status === "submitted") {
          readyForRedirect = true;
          break;
        }
        if (refreshed.session.status === "runtime_failed") {
          throw new Error(refreshed.session.runtime_failure_reason || "Submission finalization failed.");
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
      }
      if (!readyForRedirect) {
        throw new Error("Submission finalization timed out before the frozen artifact was ready.");
      }
      router.push(`/candidate/report/${response.report.id}`);
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Submission failed.");
      setStatus("Submission failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function loadMilestones() {
    const res = await apiFetch<any[]>(`/candidate/sessions/${sessionId}/checkpoints`);
    if (res) setMilestones(res);
  }

  useEffect(() => {
    if (sidebarTab === "milestones") {
      void loadMilestones();
    }
  }, [sidebarTab, sessionId]);

  async function restoreMilestone(checkpointId: string) {
    if (!window.confirm("Restore this milestone? Your current workspace will be overwritten.")) return;
    try {
      await apiSend(`/candidate/sessions/${sessionId}/checkpoints/${checkpointId}/restore`, {
        method: "POST"
      });
      await refreshTree();
      if (selectedPath) {
        const file = await apiFetch<WorkspaceFileResponse>(
          `/candidate/sessions/${sessionId}/workspace/file?path=${encodeURIComponent(selectedPath)}`
        );
        if (file) {
          setCenterTab("editor");
          setContent(file.file.content);
          setSavedContent(file.file.content);
          setFileUpdatedAt(file.file.updated_at);
        } else {
          setSelectedPath(null);
          setCenterTab("editor");
          setContent("");
        }
      }
      setStatus("Milestone restored.");
    } catch (e) {
      setError("Failed to restore milestone");
    }
  }

  async function refreshTree() {
    const tree = await apiFetch<WorkspaceTreeResponse>(`/candidate/sessions/${sessionId}/workspace/tree`);
    if (!tree) return;
    setSession(tree.session);
    setItems(tree.items);
  }

  function applyAssistantFile(file: AssistantChangedFile) {
    startTransition(() => {
      setSelectedPath(file.path);
      setCenterTab("editor");
      setContent(file.content);
      setSavedContent(file.content);
      setFileUpdatedAt(file.updated_at);
      setAutosaveState("saved");
      setOpenTabs((current) => (current.includes(file.path) ? current : [...current, file.path]));
    });
  }

  async function performSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setIsSearching(true);
    try {
      const res = await apiFetch<any>(`/candidate/sessions/${sessionId}/workspace/search?query=${encodeURIComponent(searchQuery)}`);
      setSearchResults(res?.results || []);
    } catch (err) {
      setError("Search failed");
    } finally {
      setIsSearching(false);
    }
  }

  async function createNewFile(parentPath: string = "", e?: React.MouseEvent) {
    if (e) e.stopPropagation();
    const name = window.prompt("Enter new file or directory name:");
    if (!name) return;
    const path = parentPath ? `${parentPath}/${name}` : name;
    try {
      await apiSend(`/candidate/sessions/${sessionId}/workspace/file`, {
        method: "PUT",
        body: JSON.stringify({ path, content: "" }),
      });
      await refreshTree();
      if (!name.endsWith("/")) {
        await openFile(path);
      }
    } catch (e) {
      setError("Failed to create file");
    }
  }

  async function renameFile(oldPath: string, e: React.MouseEvent) {
    e.stopPropagation();
    const newPath = window.prompt("Enter new path:", oldPath);
    if (!newPath || newPath === oldPath) return;
    try {
      await apiSend(`/candidate/sessions/${sessionId}/workspace/file/rename`, {
        method: "POST",
        body: JSON.stringify({ old_path: oldPath, new_path: newPath }),
      });
      if (selectedPath === oldPath) {
        setSelectedPath(newPath);
        setCenterTab("editor");
      }
      await refreshTree();
    } catch (e) {
      setError("Failed to rename file");
    }
  }

  async function deleteFile(path: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!window.confirm(`Delete ${path}?`)) return;
    try {
      await apiSend(`/candidate/sessions/${sessionId}/workspace/file?path=${encodeURIComponent(path)}`, {
        method: "DELETE",
      });
      if (selectedPath === path || selectedPath?.startsWith(`${path}/`)) {
        setSelectedPath(null);
        setCenterTab("editor");
        setContent("");
      }
      await refreshTree();
    } catch (e) {
      setError("Failed to delete file");
    }
  }

  async function startPreview(mode: "open" | "recompile" = "open") {
    setBusyAction("preview");
    setError(null);
    setStatus(mode === "recompile" ? "Recompiling preview..." : "Opening preview...");
    try {
      const response = await apiSend<SessionEnvelope & { preview: PreviewSummary }>(
        `/candidate/sessions/${sessionId}/preview/start`,
        { method: "POST" },
      );
      setSession(response.session);
      if (response.preview.status === "ready") {
        setPreviewFrameVersion(Date.now());
      }
      setStatus(response.preview.status === "ready" ? "Preview ready." : mode === "recompile" ? "Preview recompiling..." : "Preview opening...");
    } catch (previewError) {
      setError(previewError instanceof Error ? previewError.message : "Preview failed to start.");
      setStatus("Preview failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function recompilePreview() {
    if (dirty && selectedPath) {
      const saved = await saveFile();
      if (!saved) return;
    }
    setRightPanelTab("preview");
    setRightRailOpen(true);
    await startPreview(preview?.status === "ready" ? "recompile" : "open");
  }

  async function stopPreview() {
    setBusyAction("preview-stop");
    setError(null);
    setStatus("Stopping preview...");
    try {
      const response = await apiSend<SessionEnvelope & { preview: PreviewSummary }>(
        `/candidate/sessions/${sessionId}/preview/stop`,
        { method: "POST" },
      );
      setSession(response.session);
      setStatus("Preview stopped.");
    } catch (previewError) {
      setError(previewError instanceof Error ? previewError.message : "Preview failed to stop.");
      setStatus("Preview stop failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function retryProvisioning() {
    setBusyAction("retry");
    setError(null);
    setStatus("Retrying runtime provisioning...");
    try {
      const response = await apiSend<SessionEnvelope>(`/candidate/sessions/${sessionId}/retry`, { method: "POST" });
      setSession(response.session);
      setStatus("Runtime retry started.");
    } catch (retryError) {
      setError(retryError instanceof Error ? retryError.message : "Retry failed.");
      setStatus("Retry failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function sendAssistantPrompt() {
    const prompt = assistantDraft.trim();
    if (!prompt || !ready) return;

    if (dirty && selectedPath) {
      const saved = await saveFile();
      if (!saved) return;
    }

    setBusyAction("assistant");
    setError(null);
    setRightPanelTab("assistant");
    setRightRailOpen(true);
    setAssistantDraft("");
    setAssistantMessages((current) => [...current, { role: "me", body: prompt }]);
    setStatus("Applying assistant changes...");

    try {
      const response = await apiSend<WorkspaceAssistantResponse>(`/candidate/sessions/${sessionId}/assistant`, {
        method: "POST",
        body: JSON.stringify({
          prompt,
          selected_path: selectedPath,
          open_paths: openTabs,
        }),
      });

      const changedFiles = response.assistant.changed_files ?? [];
      const assistantBody = response.assistant.summary.trim() || (changedFiles.length ? "Updated the workspace." : "Reviewed the request but did not change any files.");
      setSession(response.session);
      setAssistantMessages((current) => [
        ...current,
        {
          role: "assistant",
          body: assistantBody,
          changedFiles,
          suggestedCommand: response.assistant.suggested_command,
          followUp: response.assistant.follow_up,
        },
      ]);

      if (response.assistant.suggested_command.trim()) {
        setCommand(response.assistant.suggested_command.trim());
      }
      await refreshTree();

      const preferredChangedFile =
        changedFiles.find((file) => file.path === selectedPath) ??
        changedFiles[0];

      if (preferredChangedFile) {
        applyAssistantFile(preferredChangedFile);
        setStatus(`Assistant updated ${preferredChangedFile.path}.`);
      } else {
        setStatus("Assistant response recorded.");
      }
    } catch (assistantError) {
      const message = assistantError instanceof Error ? assistantError.message : "Assistant request failed.";
      setError(message);
      setAssistantDraft(prompt);
      setAssistantMessages((current) => [
        ...current,
        {
          role: "assistant",
          body: `Request failed: ${message}`,
        },
      ]);
      setStatus("Assistant request failed.");
    } finally {
      setBusyAction(null);
    }
  }

  function toggleDirectory(path: string) {
    setExpandedDirs((current) => ({
      ...current,
      [path]: !current[path],
    }));
  }

  function toggleTerminal() {
    setTerminalOpen((current) => !current);
  }

  function startTerminalResize(clientY: number) {
    terminalResizeStart.current = { startY: clientY, startHeight: terminalHeight };
    setIsResizingTerminal(true);
  }

  const files = items.filter((item) => item.type === "file");
  const tree = buildWorkspaceTree(items);
  const latestResultText = result
    ? [result.stdout?.trim(), result.stderr?.trim()].filter(Boolean).join("\n\n") || "Command produced no output."
    : "Run a command or the test suite to inspect real runtime feedback.";
  const autosaveLabel = autosaveCopy(autosaveState, dirty);
  const timerShortLabel = timerLabel.replace("remaining", "left");
  const checkRows = buildCheckRows(result, latestResultText);
  const problemCount = checkRows.filter((row) => row.status === "fail").length + (error ? 1 : 0);
  const starterAssistantMessage: AssistantMessage = {
    role: "assistant",
    body:
      recommendedAction === "save"
        ? "Save first so checks and preview reflect the current draft. Then ask for a narrow edit or a focused test addition."
        : recommendedAction === "test"
          ? "Ask for a targeted fix or missing test coverage, then run checks immediately."
          : recommendedAction === "preview"
            ? "The workspace is stable enough to ask for polishing or reviewer-facing cleanup before you refresh preview."
            : "Ask for a narrow code change, a bug fix, or a focused test addition. The assistant edits files directly in this workspace.",
  };
  const assistantTranscript = assistantMessages.length ? assistantMessages : [starterAssistantMessage];

  const renderTree = (nodes: WorkspaceTreeNode[], depth = 0): JSX.Element[] =>
    nodes.map((node) => {
      if (node.type === "directory") {
        const expanded = expandedDirs[node.path] ?? depth === 0;
        const containsSelection = Boolean(selectedPath && (selectedPath === node.path || selectedPath.startsWith(`${node.path}/`)));

        return (
          <div className="relative group" key={node.path}>
            <button
              className={cn(
                "flex w-full items-center gap-2 rounded-[16px] border px-3 py-2 text-left text-xs transition",
                containsSelection
                  ? "border-indigo-400/18 bg-[linear-gradient(180deg,rgba(123,137,255,0.12),rgba(123,137,255,0.04))] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
                  : "border-transparent text-slate-300 hover:border-white/8 hover:bg-white/[0.04] hover:text-white",
              )}
              onClick={() => toggleDirectory(node.path)}
              style={{ paddingLeft: `${12 + depth * 14}px` }}
              type="button"
            >
              <span className="w-3 shrink-0 font-mono text-[10px] text-slate-500">{expanded ? "v" : ">"}</span>
              <span
                className={cn(
                  "inline-flex h-4 w-4 shrink-0 rounded-[6px] border",
                  expanded ? "border-indigo-400/28 bg-indigo-400/16" : "border-fuchsia-400/18 bg-fuchsia-400/10",
                )}
              />
              <span className="truncate flex-1 font-medium">{node.name}</span>
              <div className="hidden items-center gap-1 group-hover:flex">
                <div 
                  className="rounded-full border border-white/10 px-1.5 py-0.5 text-[10px] text-slate-400 transition hover:border-white/16 hover:bg-white/10 hover:text-white"
                  onClick={(e) => createNewFile(node.path, e)}
                  title="New File"
                >+</div>
                <div 
                  className="rounded-full border border-white/10 px-1.5 py-0.5 text-[10px] text-slate-400 transition hover:border-rose-400/20 hover:bg-rose-500/20 hover:text-rose-300"
                  onClick={(e) => deleteFile(node.path, e)}
                  title="Delete"
                >x</div>
              </div>
            </button>
            {expanded ? <div className="space-y-1 border-l border-white/6">{renderTree(node.children, depth + 1)}</div> : null}
          </div>
        );
      }

      const extension = fileExtensionLabel(node.path);

      return (
        <div className="relative group" key={node.path}>
          <button
            className={cn(
              "flex w-full items-center gap-2 rounded-[16px] border px-3 py-2 text-left text-xs transition",
              selectedPath === node.path
                ? "border-indigo-400/24 bg-[linear-gradient(180deg,rgba(123,137,255,0.18),rgba(123,137,255,0.08))] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
                : "border-transparent bg-transparent text-slate-400 hover:border-white/8 hover:bg-white/[0.04] hover:text-slate-100",
            )}
            onClick={() => void openFile(node.path)}
            style={{ paddingLeft: `${26 + depth * 14}px` }}
            type="button"
          >
            <span
              className={cn(
                "inline-flex min-w-9 shrink-0 items-center justify-center rounded-full border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em]",
                fileBadgeTone(extension),
              )}
            >
              {extension.slice(0, 3)}
            </span>
            <span className="truncate flex-1 text-left">{node.name}</span>
            <div className="hidden items-center gap-1 group-hover:flex">
              <div 
                className="rounded-full border border-white/10 px-1.5 py-0.5 text-[10px] text-slate-400 transition hover:border-white/16 hover:bg-white/10 hover:text-white"
                onClick={(e) => renameFile(node.path, e)}
                title="Rename"
              >E</div>
              <div 
                className="rounded-full border border-white/10 px-1.5 py-0.5 text-[10px] text-slate-400 transition hover:border-rose-400/20 hover:bg-rose-500/20 hover:text-rose-300"
                onClick={(e) => deleteFile(node.path, e)}
                title="Delete"
              >x</div>
            </div>
          </button>
        </div>
      );
    });

  return (
    <main className="h-[100dvh] w-full overflow-hidden bg-[#080a10] text-slate-100">
      <section className="mx-auto flex h-full max-w-[2050px] flex-col overflow-hidden border-x border-white/6 bg-[linear-gradient(180deg,#0d1018_0%,#090c13_100%)] shadow-[0_40px_120px_rgba(0,0,0,0.45)]">
        <header className="border-b border-[rgba(154,167,255,0.14)] bg-[linear-gradient(180deg,rgba(18,22,33,0.98),rgba(11,14,22,0.97))] backdrop-blur-xl">
          <div className="flex flex-wrap items-start gap-3 px-4 py-3">
            <div className="flex items-center gap-2">
              <button
                className={cn(
                  "rounded-full border px-3 py-1.5 text-[11px] font-medium transition",
                  leftRailOpen ? "border-indigo-300/30 bg-indigo-400/12 text-indigo-100" : "border-white/10 bg-white/[0.04] text-slate-300 hover:bg-white/[0.08]",
                )}
                onClick={() => setLeftRailOpen((current) => !current)}
                type="button"
              >
                Explorer
              </button>
              {previewEnabled ? (
                <button
                  className={cn(
                    "rounded-full border px-3 py-1.5 text-[11px] font-medium transition",
                    rightPanelTab === "preview"
                      ? "border-indigo-300/30 bg-indigo-400/12 text-indigo-100"
                      : "border-white/10 bg-white/[0.04] text-slate-300 hover:bg-white/[0.08]",
                  )}
                  onClick={() => setRightPanelTab("preview")}
                  type="button"
                >
                  Preview
                </button>
              ) : null}
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="workspace-label rounded-full border border-white/8 bg-white/[0.03] px-3 py-1">Project preview</span>
                <span className="workspace-chip border-indigo-300/22 bg-indigo-400/10 text-indigo-100">{canonicalAssignmentBrief.roleFocus}</span>
                <span className="workspace-chip border-fuchsia-400/24 bg-fuchsia-500/10 text-fuchsia-200">AI tracked</span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <div className="min-w-0 truncate text-[1.1rem] font-medium tracking-[-0.03em] text-slate-50">{workspaceTitle}</div>
                {track?.version ? <span className="workspace-chip font-mono text-[10px] tracking-[0.16em] text-slate-300">{track.version}</span> : null}
                {hasChecksRun ? (
                  <span
                    className={cn(
                      "workspace-chip",
                      checksPassed ? "border-emerald-400/24 bg-emerald-500/10 text-emerald-200" : "border-amber-400/24 bg-amber-500/10 text-amber-200",
                    )}
                  >
                    {typeof result?.passed_tests === "number"
                      ? `${result.passed_tests}/${result.total_tests ?? result.passed_tests} checks`
                      : checksPassed
                        ? "Checks passed"
                        : "Checks need attention"}
                  </span>
                ) : null}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
                <span className="truncate font-mono text-slate-300" data-testid="workspace-status">
                  {selectedFileDisplay}
                </span>
                <span className="hidden text-slate-500 xl:inline">•</span>
                <span>{workspaceStateLabel}</span>
              </div>
            </div>

            <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
              <div className="workspace-card-muted rounded-[18px] px-4 py-2">
                <div className="flex items-center gap-2 font-mono text-sm text-slate-100">
                  <span className="text-amber-300">○</span>
                  <span>{timerShortLabel}</span>
                </div>
              </div>
              <div className="workspace-card-muted rounded-[18px] px-4 py-2">
                <div className="text-sm font-medium text-emerald-300">{autosaveLabel}</div>
              </div>
              <span className={cn("workspace-chip", badgeTone(session?.status ?? "pending"))} data-testid="session-state">
                {session?.status ?? "loading"}
              </span>
              <div className="hidden items-center gap-2 xl:flex">
                <button
                  className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-medium text-slate-200 transition hover:-translate-y-0.5 hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-50"
                  data-testid="run-tests-button"
                  disabled={busyAction !== null || !ready}
                  onClick={() => void runCommand("test")}
                  type="button"
                >
                  {busyAction === "test" ? "Running..." : "Run checks"}
                </button>
                {previewEnabled ? (
                  <button
                    className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-medium text-slate-200 transition hover:-translate-y-0.5 hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-50"
                    data-testid="start-preview-button"
                    disabled={busyAction !== null || !ready}
                    onClick={() => void recompilePreview()}
                    type="button"
                  >
                    {busyAction === "preview" ? "Opening..." : "Preview"}
                  </button>
                ) : null}
                <button
                  className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-medium text-slate-200 transition hover:-translate-y-0.5 hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-50"
                  data-testid="checkpoint-button"
                  disabled={busyAction !== null || !ready}
                  onClick={() => void createCheckpoint()}
                  type="button"
                >
                  {busyAction === "checkpoint" ? "Saving..." : "Milestone"}
                </button>
              </div>
              <button
                className="inline-flex items-center rounded-[18px] border border-indigo-300/28 bg-[linear-gradient(135deg,#8b96ff,#a86dff)] px-5 py-3 text-sm font-semibold text-slate-950 shadow-[0_18px_44px_rgba(139,150,255,0.24)] transition hover:-translate-y-0.5 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                data-testid="submit-assessment-button"
                disabled={busyAction !== null || session?.status === "submitted" || !ready}
                onClick={() => {
                  setCenterTab("review");
                }}
                type="button"
              >
                {busyAction === "submit" ? "Submitting..." : isSubmitted ? "Submitted" : "Submit"}
              </button>
            </div>
          </div>
        </header>

        {!ready ? (
          <div className="flex flex-1 items-center justify-center p-8">
            <div className="workspace-card mx-auto max-w-xl rounded-[30px] p-8 text-center">
              <div className="workspace-label">Workspace</div>
              <div className="mt-4 text-2xl font-semibold text-white">{session?.environment_summary?.readiness ?? session?.status ?? "pending"}</div>
              <p className="mt-3 text-sm leading-7 text-slate-400">
                {session?.runtime_failure_reason ?? "Your build environment is preparing the project workspace."}
              </p>
              {session?.latest_runtime_job?.error ? <p className="mt-3 text-sm text-rose-300">{session.latest_runtime_job.error}</p> : null}
              {session?.status === "runtime_failed" ? (
                <button
                  className="mt-5 rounded-full border border-amber-400/20 bg-amber-500/10 px-4 py-2 text-sm font-medium text-amber-200 transition hover:-translate-y-0.5 hover:bg-amber-500/15"
                  data-testid="retry-runtime-button"
                  disabled={busyAction !== null}
                  onClick={() => void retryProvisioning()}
                  type="button"
                >
                  {busyAction === "retry" ? "Retrying..." : "Retry build"}
                </button>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1">
            {leftRailOpen ? (
            <aside className="flex min-h-0 w-[252px] shrink-0 flex-col border-r border-[rgba(154,167,255,0.12)] bg-[linear-gradient(180deg,#0d1119_0%,#0b0e15_100%)] shadow-[inset_-1px_0_0_rgba(255,255,255,0.03)] 2xl:w-[272px]">
              <div className="border-b border-[rgba(154,167,255,0.12)] px-4 py-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="workspace-label">Explorer</div>
                    <div className="mt-2 font-mono text-sm uppercase tracking-[0.14em] text-slate-200">{workspaceTitle}</div>
                  </div>
                  <span className="workspace-chip font-mono text-[10px] text-slate-300">{files.length} files</span>
                </div>
                <div className="mt-4 flex items-center gap-2">
                  <button
                    className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[11px] text-slate-300 transition hover:bg-white/[0.08]"
                    onClick={() => void createNewFile("")}
                    type="button"
                  >
                    New file
                  </button>
                  <button
                    className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[11px] text-slate-300 transition hover:bg-white/[0.08]"
                    onClick={() => setLeftRailOpen(false)}
                    type="button"
                  >
                    Hide
                  </button>
                </div>
              </div>

              <div className="px-3 pt-3">
                <div className="grid grid-cols-3 gap-1 rounded-[18px] border border-white/8 bg-black/20 p-1">
                  {[
                    ["files", "Files"],
                    ["search", "Search"],
                    ["milestones", "Milestones"],
                  ].map(([value, label]) => (
                    <button
                      className={cn(
                        "rounded-[14px] px-2 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] transition",
                        sidebarTab === value
                          ? "bg-[linear-gradient(135deg,rgba(123,137,255,0.2),rgba(168,109,255,0.18))] text-slate-50 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
                          : "text-slate-500 hover:text-slate-200",
                      )}
                      key={value}
                      onClick={() => setSidebarTab(value as "files" | "search" | "milestones")}
                      type="button"
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="workspace-scrollbar min-h-0 flex-1 overflow-y-auto px-3 pb-3 pt-3">
                {sidebarTab === "files" ? (
                  <div className="space-y-1">{tree.length ? renderTree(tree) : <div className="rounded-[16px] border border-dashed border-white/10 bg-white/[0.03] px-3 py-3 text-xs text-slate-500">Files appear here once the workspace loads.</div>}</div>
                ) : sidebarTab === "search" ? (
                  <div>
                    <form onSubmit={(e) => void performSearch(e)}>
                      <input
                        autoFocus
                        className="w-full rounded-[16px] border border-white/10 bg-[#090c13] px-3 py-2.5 text-xs text-slate-100 outline-none transition focus:border-indigo-400/40"
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search files..."
                        value={searchQuery}
                      />
                      <button className="hidden" type="submit">
                        Search
                      </button>
                    </form>
                    <div className="mt-3 space-y-2">
                      {isSearching ? (
                        <div className="text-xs text-slate-500">Searching...</div>
                      ) : searchResults.length > 0 ? (
                        searchResults.map((res, i) => (
                          <button
                            className="workspace-card-muted w-full rounded-[18px] px-3 py-3 text-left text-[11px] transition hover:-translate-y-0.5"
                            key={i}
                            onClick={() => void openFile(res.path)}
                            type="button"
                          >
                            <div className="font-medium text-slate-200">
                              {res.path} <span className="text-slate-500">:{res.line_number}</span>
                            </div>
                            <div className="mt-1 truncate font-mono text-[10px] text-slate-400">{res.line_content}</div>
                          </button>
                        ))
                      ) : searchQuery ? (
                        <div className="text-xs text-slate-500">No results found.</div>
                      ) : (
                        <div className="text-xs text-slate-500">Search the workspace by path or content.</div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {milestones.length > 0 ? (
                      milestones.map((ms, i) => (
                        <div className="workspace-card-muted rounded-[18px] p-3" key={i}>
                          <div className="text-sm font-medium text-slate-200">{ms.label}</div>
                          <div className="mt-1 text-[11px] text-slate-500">{new Date(ms.created_at).toLocaleString()}</div>
                          <button
                            className="mt-3 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[11px] text-slate-200 transition hover:bg-white/[0.08]"
                            onClick={() => void restoreMilestone(ms.checkpoint_id)}
                            type="button"
                          >
                            Restore
                          </button>
                        </div>
                      ))
                    ) : (
                      <div className="rounded-[16px] border border-dashed border-white/10 bg-white/[0.03] px-3 py-4 text-xs text-slate-500">
                        No milestones captured yet.
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="border-t border-[rgba(154,167,255,0.12)] p-3">
                <div className="workspace-card rounded-[20px] p-4">
                  <div className="workspace-label">Workspace</div>
                  <p className="mt-2 text-[11px] leading-5 text-slate-400">
                    This environment is deliberately code-first: files, editor, terminal, preview, assistant, and publish.
                  </p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {dimensions.slice(0, 4).map((dimension) => (
                      <span className="workspace-chip text-[10px]" key={dimension.key}>
                        {dimension.label}
                      </span>
                    ))}
                  </div>
                  <div className="mt-3 text-[11px] text-slate-400">
                    Workspace <span className="font-mono text-slate-200" data-testid="workspace-id">{session?.workspace_id ?? "pending"}</span>
                  </div>
                </div>
              </div>
            </aside>
            ) : null}

            <section className="flex min-h-0 flex-1 flex-col bg-[linear-gradient(180deg,#090c13_0%,#080a11_100%)]">
              <div className="border-b border-[rgba(154,167,255,0.12)] bg-[linear-gradient(180deg,#111623_0%,#0d1119_100%)]">
                <div className="workspace-scrollbar flex min-h-13 items-end gap-1.5 overflow-x-auto px-3 pt-2">
                  {openTabs.map((path) => {
                    const isActive = centerTab === "editor" && selectedPath === path;
                    const isDirtyTab = isActive && dirty;
                    const extension = fileExtensionLabel(path);

                    return (
                      <div
                        className={cn(
                          "inline-flex items-center gap-2 rounded-t-[18px] border border-b-0 px-3.5 py-2.5 text-xs transition",
                          isActive
                            ? "border-indigo-300/20 bg-[linear-gradient(180deg,#181d2a_0%,#111623_100%)] text-slate-50 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
                            : "border-transparent bg-transparent text-slate-500 hover:text-slate-200",
                        )}
                        key={path}
                      >
                        <button className="inline-flex items-center gap-2" onClick={() => void openFile(path)} type="button">
                          <span className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-white/10 bg-white/[0.04] text-[9px] font-semibold uppercase text-slate-300">
                            {extension.slice(0, 1)}
                          </span>
                          <span>{fileLabel(path)}</span>
                          {isDirtyTab ? <span className="h-2 w-2 rounded-full bg-amber-300" /> : null}
                        </button>
                        <button
                          aria-label={`Close ${fileLabel(path)}`}
                          className="rounded-full px-1.5 py-0.5 text-[11px] text-slate-500 transition hover:bg-white/[0.06] hover:text-slate-200"
                          onClick={() => void closeTab(path)}
                          type="button"
                        >
                          ×
                        </button>
                      </div>
                    );
                  })}
                  <div className="ml-auto hidden items-center gap-2 pb-2 pr-1 text-[10px] text-slate-500 xl:flex">
                    <span className="workspace-chip bg-white/[0.03] font-mono text-[10px] text-slate-300">{centerTab === "review" ? "publish review" : "active editor"}</span>
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/6 px-4 py-2">
                  <div className="min-w-0 truncate font-mono text-[11px] text-slate-400">{selectedFileDisplay}</div>
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
                    {centerTab === "review" ? "Confirm artifact before publish" : recommendedActionCopy.label}
                  </div>
                </div>
              </div>

              {centerTab === "prompt" ? (
                <div className="min-h-0 flex-1 overflow-y-auto">
                  <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-4">
                    <div className="rounded-[22px] border border-white/10 bg-[linear-gradient(180deg,#141824,#10141d)] p-5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full border border-indigo-400/30 bg-indigo-500/12 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-indigo-200">
                          {canonicalAssignmentBrief.assignmentLabel}
                        </span>
                        <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-[10px] text-slate-300">
                          {canonicalAssignmentBrief.roleFocus}
                        </span>
                      </div>
                      <h2 className="mt-3 text-2xl font-semibold tracking-tight text-white">{track?.title ?? canonicalAssignmentBrief.title}</h2>
                      <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">{canonicalAssignmentBrief.overview}</p>
                      <div className="mt-4 grid gap-3 md:grid-cols-4">
                        {promptProjectFacts.map(([label, value]) => (
                          <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3" key={label}>
                            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
                            <div className="mt-1.5 font-mono text-[11px] text-slate-300">{value}</div>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
                      <div className="space-y-4">
                        <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">What you are being asked to do</div>
                          <p className="mt-3 text-sm leading-6 text-slate-300">{canonicalAssignmentBrief.framing}</p>
                        </div>

                        <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Implementation requirements</div>
                          <div className="mt-3 grid gap-2">
                            {assignmentRequirements.map((requirement) => (
                              <div className="rounded-xl border border-white/10 bg-[#0f131c] px-3 py-3 text-xs leading-5 text-slate-300" key={requirement}>
                                {requirement}
                              </div>
                            ))}
                          </div>
                        </div>

                        <div className="grid gap-4 lg:grid-cols-2">
                          <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Deliverables</div>
                            <div className="mt-3 space-y-2">
                              {assignmentDeliverables.map((deliverable) => (
                                <div className="rounded-xl border border-white/10 bg-[#0f131c] px-3 py-3 text-xs leading-5 text-slate-300" key={deliverable}>
                                  {deliverable}
                                </div>
                              ))}
                            </div>
                          </div>

                          <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">How reviewers score the work</div>
                            <div className="mt-3 space-y-2">
                              {rubricDimensions.map((dimension) => (
                                <div className="rounded-xl border border-white/10 bg-[#0f131c] p-3" key={dimension.label}>
                                  <div className="flex items-center justify-between gap-3">
                                    <div className="text-xs font-semibold text-white">{dimension.label}</div>
                                    <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-slate-300">{dimension.weight}</span>
                                  </div>
                                  <p className="mt-2 text-[11px] leading-5 text-slate-400">{dimension.description}</p>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>

                        <div className="grid gap-4 lg:grid-cols-[0.96fr_1.04fr]">
                          <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Guardrails</div>
                            <div className="mt-3 space-y-2">
                              {assignmentGuardrails.map((item) => (
                                <div className="rounded-xl border border-white/10 bg-[#0f131c] px-3 py-3 text-xs leading-5 text-slate-300" key={item}>
                                  {item}
                                </div>
                              ))}
                            </div>
                          </div>

                          <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Recommended approach</div>
                            <div className="mt-3 space-y-2">
                              {assignmentWorkflow.map((step, index) => (
                                <div className="rounded-xl border border-white/10 bg-[#0f131c] p-3" key={step.title}>
                                  <div className="flex items-center gap-3">
                                    <div className="flex h-6 w-6 items-center justify-center rounded-full border border-indigo-400/25 bg-indigo-500/12 text-[11px] font-semibold text-indigo-200">
                                      {index + 1}
                                    </div>
                                    <div className="text-xs font-semibold text-white">{step.title}</div>
                                  </div>
                                  <p className="mt-2 text-[11px] leading-5 text-slate-400">{step.detail}</p>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="space-y-4 xl:sticky xl:top-4 xl:self-start">
                        <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Assignment snapshot</div>
                          <div className="mt-2 text-xl font-semibold text-white">{canonicalAssignmentBrief.expectedTime} take-home</div>
                          <div className="mt-4 space-y-3">
                            {promptEnvironmentFacts.map(([label, value]) => (
                              <div key={label}>
                                <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
                                <div className="mt-1 text-xs font-medium text-slate-200">{value}</div>
                              </div>
                            ))}
                          </div>
                        </div>

                        <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">When you are ready</div>
                          <p className="mt-2 text-xs leading-5 text-slate-400">
                            Open the seeded implementation file and start making the smallest correct changes first. The workspace is already provisioned.
                          </p>
                          <button
                            className="mt-4 inline-flex items-center rounded-lg bg-[linear-gradient(135deg,#8795ff,#9aa7ff)] px-3 py-2 text-xs font-semibold text-slate-950 transition hover:brightness-110"
                            onClick={() => {
                              if (selectedPath) {
                                setCenterTab("editor");
                              }
                            }}
                            type="button"
                          >
                            {selectedPath ? `Open ${fileLabel(selectedPath)}` : "Select a file from the explorer"}
                          </button>
                        </div>

                        <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Submission flow</div>
                              <p className="mt-2 text-xs leading-5 text-slate-400">
                                Publish from the final review page after you confirm checks, preview, and the note that will travel with the artifact.
                              </p>
                            </div>
                            <span className={cn("rounded-full border px-2 py-0.5 text-[10px]", submitReady ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : "border-amber-500/20 bg-amber-500/10 text-amber-300")}>
                              {submitReady ? "ready to publish" : "review required"}
                            </span>
                          </div>
                          <button
                            className="mt-4 inline-flex items-center rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10"
                            onClick={() => setCenterTab("review")}
                            type="button"
                          >
                            Open final review
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ) : centerTab === "review" ? (
                <div className="min-h-0 flex-1 overflow-y-auto bg-[radial-gradient(circle_at_top,rgba(135,149,255,0.08),transparent_42%),#090c13]">
                  <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 p-5">
                    <div className="rounded-[24px] border border-[rgba(135,149,255,0.18)] bg-[linear-gradient(180deg,#131824,#0f131c)] p-6 shadow-[0_24px_64px_rgba(0,0,0,0.28)]">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">Final review checkpoint</div>
                          <h2 className="mt-2 text-3xl font-semibold tracking-tight text-white">Confirm the exact artifact recruiters will review.</h2>
                          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
                            This is the last candidate-facing step. Review the latest checks, confirm the preview state, and write the note that reviewers and employers will read with your project credential.
                          </p>
                        </div>
                        <span className={cn("rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em]", submitReady ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : "border-amber-500/20 bg-amber-500/10 text-amber-300")}>
                          {submitReady ? "Ready to publish" : "Needs attention"}
                        </span>
                      </div>
                    </div>

                    <div className="grid gap-4 md:grid-cols-4">
                      {[
                        ["Checks", hasChecksRun ? (checksPassed ? "passing" : "attention needed") : "not run"],
                        ["Preview", previewEnabled ? (previewCurrent ? "up to date" : previewReady ? "stale" : "not compiled") : "not required"],
                        ["Reflection", reflectionReady ? "complete" : "missing"],
                        ["Artifact", selectedPath ? `${openTabs.length || 1} active file view${openTabs.length === 1 ? "" : "s"}` : "no file selected"],
                      ].map(([label, value]) => (
                        <div className="rounded-[18px] border border-white/10 bg-white/[0.035] p-4" key={label}>
                          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
                          <div className="mt-2 text-sm font-medium text-slate-100">{value}</div>
                        </div>
                      ))}
                    </div>

                    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
                      <div className="space-y-4">
                        <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Recommended next action</div>
                          <div className={cn("mt-2 text-sm font-medium", recommendedActionCopy.tone)}>{recommendedActionCopy.label}</div>
                          <p className="mt-2 text-xs leading-5 text-slate-400">{recommendedActionCopy.detail}</p>
                          <div className="mt-4 flex flex-wrap gap-2">
                            <button
                              className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
                              disabled={busyAction !== null || !ready}
                              onClick={() => void runCommand("test")}
                              type="button"
                            >
                              Run checks again
                            </button>
                            {previewEnabled ? (
                              <button
                                className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
                                disabled={busyAction !== null || !ready}
                                onClick={() => void recompilePreview()}
                                type="button"
                              >
                                {previewReady ? "Refresh preview" : "Compile preview"}
                              </button>
                            ) : null}
                            <button
                              className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10"
                              onClick={() => setCenterTab("editor")}
                              type="button"
                            >
                              Back to code
                            </button>
                          </div>
                        </div>

                        <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Submission checklist</div>
                          <div className="mt-3 space-y-2">
                            {[
                              { key: "brief_reviewed", label: "Brief confirmed", complete: submissionChecklist.brief_reviewed },
                              { key: "checks_run", label: "Checks recorded", complete: submissionChecklist.checks_run },
                              { key: "preview_current", label: previewEnabled ? "Preview up to date" : "Preview not required", complete: submissionChecklist.preview_current },
                              { key: "reflection_ready", label: "Submission note complete", complete: submissionChecklist.reflection_ready },
                            ].map(({ key, label, complete }) => (
                              <div className="flex items-center justify-between rounded-xl border border-white/10 bg-[#0f131c] px-3 py-3 text-xs" key={key}>
                                <span className="text-slate-300">{label}</span>
                                <span className={complete ? "text-emerald-300" : "text-slate-500"}>{complete ? "done" : "pending"}</span>
                              </div>
                            ))}
                          </div>
                          <label className="mt-4 flex items-start gap-3 rounded-xl border border-white/10 bg-[#0f131c] px-3 py-3 text-xs text-slate-300">
                            <input
                              checked={briefReviewed}
                              className="mt-0.5 h-3.5 w-3.5 rounded border-white/20 bg-[#0b0e15] text-indigo-400"
                              data-testid="submission-checklist-brief"
                              onChange={(event) => setBriefReviewed(event.target.checked)}
                              type="checkbox"
                            />
                            <span>I reviewed the brief and understand what evidence this project credential is supposed to create.</span>
                          </label>
                        </div>

                        <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">What will be frozen</div>
                          <div className="mt-3 grid gap-3 sm:grid-cols-2">
                            <div className="rounded-xl border border-white/10 bg-[#0f131c] p-3">
                              <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Latest checks</div>
                              <div className="mt-2 text-sm font-medium text-slate-100">
                                {hasChecksRun
                                  ? typeof result?.passed_tests === "number"
                                    ? `${result.passed_tests}/${result.total_tests ?? result.passed_tests} checks recorded`
                                    : checksPassed
                                      ? "Latest checks passed"
                                      : "Checks need attention"
                                  : "No checks recorded yet"}
                              </div>
                              <p className="mt-2 text-xs leading-5 text-slate-400">
                                {hasChecksRun ? "The latest recorded test result will be attached to the final report." : "Run checks before publishing so the report has fresh evidence."}
                              </p>
                              {hasChecksRun ? (
                                <div className="mt-3 space-y-2">
                                  {buildCheckRows(result, latestResultText).slice(0, 3).map((row) => (
                                    <div className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-2 text-[11px]" key={row.label}>
                                      <span className="text-slate-300">{row.label}</span>
                                      <span className={row.status === "pass" ? "text-emerald-300" : "text-rose-300"}>{row.status}</span>
                                    </div>
                                  ))}
                                </div>
                              ) : null}
                            </div>
                            <div className="rounded-xl border border-white/10 bg-[#0f131c] p-3">
                              <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Preview state</div>
                              <div className={cn("mt-2 text-sm font-medium", previewEnabled && !previewCurrent ? "text-amber-300" : "text-slate-100")}>
                                {previewEnabled ? (previewCurrent ? `Current at ${previewReadyLabel}` : previewReady ? "Preview is stale" : "Preview has not been compiled") : "Preview not required for this track"}
                              </div>
                              <p className="mt-2 text-xs leading-5 text-slate-400">
                                {previewEnabled
                                  ? "If the preview is stale, refresh it before you freeze the artifact."
                                  : "This track is judged from code and checks rather than a rendered preview."}
                              </p>
                              {previewEnabled ? (
                                <div className="mt-3 rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-2 text-[11px] text-slate-300">
                                  {previewReady ? `Last ready snapshot: ${previewReadyLabel}` : "No preview snapshot recorded yet."}
                                </div>
                              ) : null}
                            </div>
                            <div className="rounded-xl border border-white/10 bg-[#0f131c] p-3">
                              <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Current coding context</div>
                              <div className="mt-2 text-sm font-medium text-slate-100">{selectedPath ? fileLabel(selectedPath) : "No file selected"}</div>
                              <p className="mt-2 text-xs leading-5 text-slate-400">The frozen artifact includes the whole workspace state, but this is the file you were last working in.</p>
                            </div>
                            <div className="rounded-xl border border-white/10 bg-[#0f131c] p-3">
                              <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Trust summary</div>
                              <div className="mt-2 text-sm font-medium text-slate-100">
                                {session?.integrity_summary?.review_signals?.length
                                  ? `${session.integrity_summary.review_signals.length} signal${session.integrity_summary.review_signals.length === 1 ? "" : "s"} recorded`
                                  : session?.integrity_summary?.flags?.length
                                    ? `${session.integrity_summary.flags.length} flag${session.integrity_summary.flags.length === 1 ? "" : "s"} recorded`
                                    : "No active trust concerns"}
                              </div>
                              <p className="mt-2 text-xs leading-5 text-slate-400">Reviewers will see timeline and AI-usage context alongside the code and checks.</p>
                            </div>
                          </div>
                        </div>

                        <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Submission note</div>
                          <div className="mt-4 space-y-3">
                            <div>
                              <label className="text-[10px] uppercase tracking-[0.16em] text-slate-500">What changed</label>
                              <textarea
                                className="mt-2 min-h-[92px] w-full rounded-xl border border-white/10 bg-[#0f131c] px-3 py-3 text-xs text-slate-100 outline-none transition focus:border-indigo-400/40"
                                data-testid="candidate-summary-note"
                                onChange={(event) => setCandidateSummaryNote(event.target.value)}
                                placeholder="Summarize the core behavior you changed."
                                rows={4}
                                value={candidateSummaryNote}
                              />
                            </div>
                            <div>
                              <label className="text-[10px] uppercase tracking-[0.16em] text-slate-500">One tradeoff made</label>
                              <textarea
                                className="mt-2 min-h-[92px] w-full rounded-xl border border-white/10 bg-[#0f131c] px-3 py-3 text-xs text-slate-100 outline-none transition focus:border-indigo-400/40"
                                data-testid="candidate-tradeoff-note"
                                onChange={(event) => setTradeoffNote(event.target.value)}
                                placeholder="Explain one tradeoff you made under time pressure."
                                rows={4}
                                value={tradeoffNote}
                              />
                            </div>
                            <div>
                              <label className="text-[10px] uppercase tracking-[0.16em] text-slate-500">One thing left unfinished</label>
                              <textarea
                                className="mt-2 min-h-[92px] w-full rounded-xl border border-white/10 bg-[#0f131c] px-3 py-3 text-xs text-slate-100 outline-none transition focus:border-indigo-400/40"
                                data-testid="candidate-unfinished-note"
                                onChange={(event) => setUnfinishedWorkNote(event.target.value)}
                                placeholder="Call out a follow-up you would tackle with more time."
                                rows={4}
                                value={unfinishedWorkNote}
                              />
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="space-y-4 xl:sticky xl:top-4 xl:self-start">
                        <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Publish outcome</div>
                          <p className="mt-3 text-xs leading-5 text-slate-400">
                            Publishing freezes the workspace, generates the candidate report, and sends the artifact into recruiter review. You can still discuss tradeoffs later, but the code and recorded evidence stop changing here.
                          </p>
                          <button
                            className="mt-4 inline-flex items-center rounded-lg bg-[linear-gradient(135deg,#8795ff,#9aa7ff)] px-3 py-2 text-xs font-semibold text-slate-950 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                            data-testid="confirm-submit-assessment-button"
                            disabled={busyAction !== null || session?.status === "submitted" || !submitReady}
                            onClick={() => void submitAssessment()}
                            type="button"
                          >
                            {busyAction === "submit" ? "Submitting..." : "Freeze artifact and submit"}
                          </button>
                        </div>

                        <div className="rounded-[20px] border border-white/10 bg-white/[0.03] p-4">
                          <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Need to change something?</div>
                          <p className="mt-2 text-xs leading-5 text-slate-400">Go back to the editor or prompt, make the change, then return here to confirm the final artifact.</p>
                          <div className="mt-4 flex flex-wrap gap-2">
                            <button
                              className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-slate-100 transition hover:bg-white/10"
                              onClick={() => setCenterTab("editor")}
                              type="button"
                            >
                              Back to code
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <>
                  <div className="min-h-0 flex-1">
                    <MonacoEditor
                      height="100%"
                      language={languageForPath(selectedPath ?? "")}
                      onChange={(value) => setContent(value ?? "")}
                      options={{
                        automaticLayout: true,
                        fontSize: 13,
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                        tabSize: 4,
                        padding: { top: 12 },
                        lineNumbersMinChars: 2,
                      }}
                      theme="vs-dark"
                      value={content}
                    />
                  </div>

                  <div className="border-t border-[rgba(154,167,255,0.12)] bg-[linear-gradient(180deg,#0d1119_0%,#090c13_100%)]">
                    <div className="flex flex-wrap items-center gap-2 border-b border-[rgba(154,167,255,0.12)] px-3 py-2.5">
                      <button
                        className={cn(
                          "inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs transition",
                          terminalOpen ? "border border-white/10 bg-white/[0.08] text-slate-100" : "text-slate-400 hover:text-slate-200",
                        )}
                        onClick={() => toggleTerminal()}
                        type="button"
                      >
                        Terminal
                      </button>
                      <div className="workspace-chip bg-white/[0.03] text-xs text-slate-300">
                        Tests {typeof result?.passed_tests === "number" ? `${result.passed_tests}/${result.total_tests ?? result.passed_tests}` : "0/0"}
                      </div>
                      <div className="workspace-chip bg-white/[0.03] text-xs text-slate-300">Problems {problemCount}</div>
                      <div className="ml-auto flex flex-wrap items-center gap-2">
                        <button
                          className={actionButtonClass(recommendedAction === "save")}
                          data-testid="save-file-button"
                          disabled={!selectedPath || busyAction !== null || !dirty || !ready}
                          onClick={() => void saveFile()}
                          type="button"
                        >
                          {busyAction === "save" ? "Saving..." : "Save"}
                        </button>
                        <button
                          className={actionButtonClass(recommendedAction === "test")}
                          disabled={busyAction !== null || !ready}
                          onClick={() => void runCommand("test")}
                          type="button"
                        >
                          {busyAction === "test" ? "Running checks..." : "Run checks"}
                        </button>
                        {previewEnabled ? (
                          <button
                            className={actionButtonClass(recommendedAction === "preview")}
                            disabled={busyAction !== null || !ready}
                            onClick={() => void recompilePreview()}
                            type="button"
                          >
                            {busyAction === "preview" ? "Refreshing..." : preview?.status === "ready" ? "Refresh preview" : "Open preview"}
                          </button>
                        ) : null}
                        <button
                          className="rounded-full border border-white/10 bg-white/[0.04] px-3.5 py-2 text-xs font-medium text-slate-200 transition hover:-translate-y-0.5 hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-50"
                          disabled={busyAction !== null || !ready}
                          onClick={() => void createCheckpoint()}
                          type="button"
                        >
                          {busyAction === "checkpoint" ? "Capturing..." : "Milestone"}
                        </button>
                      </div>
                    </div>

                    {terminalOpen ? (
                      <div className="overflow-hidden" style={{ height: `${terminalHeight}px` }}>
                        <div className="hidden border-b border-[rgba(154,167,255,0.12)] xl:flex">
                          <button
                            aria-label="Resize terminal drawer"
                            className={cn(
                              "group flex h-4 w-full cursor-row-resize items-center justify-center bg-[#0b0f16] transition",
                              isResizingTerminal ? "bg-white/[0.08]" : "hover:bg-white/[0.04]",
                            )}
                            onMouseDown={(event) => {
                              event.preventDefault();
                              startTerminalResize(event.clientY);
                            }}
                            type="button"
                          >
                            <span className="h-[2px] w-16 rounded-full bg-white/10 transition group-hover:bg-indigo-200/40" />
                          </button>
                        </div>
                        <div className="flex h-full flex-col bg-[#05070d]">
                          <div className="min-h-0 flex-1 overflow-hidden p-2">
                            <XtermTerminal sessionId={sessionId} />
                          </div>
                          {result || error ? (
                            <div className="border-t border-[rgba(154,167,255,0.12)] bg-[#0d111a] px-3 py-2.5">
                              <div className="mb-2 flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
                                <span className="workspace-chip bg-white/[0.03] text-[10px] text-slate-300">{status}</span>
                                {checkRows.slice(0, 3).map((row) => (
                                  <span
                                    className={cn(
                                      "workspace-chip px-2 py-0.5 text-[10px]",
                                      row.status === "pass"
                                        ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200"
                                        : "border-rose-400/20 bg-rose-500/10 text-rose-200",
                                    )}
                                    key={row.label}
                                  >
                                    {row.label}
                                  </span>
                                ))}
                              </div>
                              <pre className="workspace-scrollbar max-h-24 overflow-auto rounded-[16px] border border-white/10 bg-[#05070d] p-3 text-[10px] leading-5 text-slate-400">{latestResultText}</pre>
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ) : (
                      <div className="px-3 py-2.5 text-[11px] text-slate-500">
                        Terminal hidden. Open it when you need runtime feedback.
                      </div>
                    )}
                  </div>
                </>
              )}
            </section>

            {rightRailOpen ? (
            <aside className="flex min-h-0 w-[320px] shrink-0 flex-col border-l border-[rgba(154,167,255,0.12)] bg-[linear-gradient(180deg,#0f131d_0%,#0d1118_100%)] shadow-[inset_1px_0_0_rgba(255,255,255,0.03)] 2xl:w-[348px]">
              <div className="border-b border-[rgba(154,167,255,0.12)] px-4 py-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="workspace-label text-fuchsia-300">{rightPanelTab === "assistant" ? "AI assistant" : "Project preview"}</div>
                    <div className="mt-2 font-mono text-sm uppercase tracking-[0.14em] text-slate-100">{rightPanelTab === "assistant" ? "Tracked review context" : "Live output"}</div>
                  </div>
                  <div className="workspace-chip border-white/10 bg-white/[0.04] font-mono text-[10px] text-slate-200">
                    {rightPanelTab === "assistant" ? "GPT-5" : "Live"}
                  </div>
                </div>
              </div>
              <div className="border-b border-fuchsia-400/24 bg-[linear-gradient(180deg,rgba(95,18,107,0.22),rgba(54,18,62,0.12))] px-4 py-3 text-sm leading-6 text-fuchsia-200">
                Tracked. Your prompts and any code you accept are shared with the reviewer.
              </div>
              <div className="px-3 py-3">
                <div className="grid grid-cols-2 gap-1 rounded-[18px] border border-white/8 bg-black/20 p-1">
                <button
                  className={cn(
                    "rounded-[14px] px-2.5 py-2 text-xs font-semibold transition",
                    rightPanelTab === "assistant"
                      ? "bg-[linear-gradient(135deg,rgba(123,137,255,0.18),rgba(168,109,255,0.18))] text-slate-100"
                      : "text-slate-400 hover:text-slate-200",
                  )}
                  onClick={() => setRightPanelTab("assistant")}
                  type="button"
                >
                  Assistant
                </button>
                <button
                  className={cn(
                    "rounded-[14px] px-2.5 py-2 text-xs font-semibold transition",
                    rightPanelTab === "preview"
                      ? "bg-[linear-gradient(135deg,rgba(123,137,255,0.18),rgba(168,109,255,0.18))] text-slate-100"
                      : "text-slate-400 hover:text-slate-200",
                  )}
                  onClick={() => setRightPanelTab("preview")}
                  type="button"
                >
                  Preview
                </button>
                </div>
              </div>

              {rightPanelTab === "assistant" ? (
                <>
                  <div className="workspace-scrollbar min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
                    {assistantTranscript.map((message, index) => (
                      <div className={cn("flex", message.role === "me" ? "justify-end" : "justify-start")} key={`${message.role}-${index}`}>
                        <div className="flex max-w-[96%] items-start gap-2">
                          {message.role === "assistant" ? (
                            <div className="mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-[14px] border border-fuchsia-400/18 bg-fuchsia-500/10 text-[10px] font-semibold uppercase tracking-[0.18em] text-fuchsia-200">
                              AI
                            </div>
                          ) : null}
                          <div className={cn("max-w-full rounded-[22px] px-4 py-3 text-xs leading-6 shadow-[0_18px_36px_rgba(0,0,0,0.2)]", message.role === "me" ? "border border-indigo-300/16 bg-[linear-gradient(180deg,#2d315a,#242848)] text-slate-100" : "workspace-card-muted text-slate-200")}>
                            <div className="mb-2 flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.18em] text-slate-500">
                              <span>{message.role === "me" ? "You" : "Assistant"}</span>
                              {message.changedFiles?.length ? <span>{message.changedFiles.length} file{message.changedFiles.length === 1 ? "" : "s"}</span> : null}
                            </div>
                          <div>{message.body}</div>
                          {message.changedFiles?.length ? (
                            <div className="mt-3 space-y-2 border-t border-white/10 pt-3">
                              {message.changedFiles.map((file) => (
                                <div className="rounded-[18px] border border-white/10 bg-[#0d1018] px-3 py-3" key={file.path}>
                                  <div className="flex items-center justify-between gap-2">
                                    <button
                                      className="truncate text-left font-medium text-slate-100 transition hover:text-white"
                                      onClick={() => applyAssistantFile(file)}
                                      type="button"
                                    >
                                      {file.path}
                                    </button>
                                    <span className="workspace-chip bg-white/[0.03] px-2 py-0.5 text-[10px] text-slate-400">
                                      {file.size} chars
                                    </span>
                                  </div>
                                  {file.summary ? <div className="mt-2 text-[11px] leading-5 text-slate-400">{file.summary}</div> : null}
                                </div>
                              ))}
                            </div>
                          ) : null}
                          {message.suggestedCommand ? (
                            <div className="mt-3 rounded-[16px] border border-white/10 bg-[#090c13] px-3 py-2.5 font-mono text-[11px] text-slate-300">
                              {message.suggestedCommand}
                            </div>
                          ) : null}
                          </div>
                          {message.role === "me" ? (
                            <div className="mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-[14px] border border-indigo-300/18 bg-indigo-400/10 text-[10px] font-semibold uppercase tracking-[0.18em] text-indigo-100">
                              Me
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ))}

                    <div className="workspace-card-muted rounded-[20px] p-4">
                      <div className="workspace-label">Suggested next prompt</div>
                      <div className="mt-3 rounded-[18px] border border-white/10 bg-[#090c13] p-3 font-mono text-xs leading-6 text-slate-200">
                        {assistantMessages[assistantMessages.length - 1]?.followUp?.trim() || "Ask for narrow diffs, failure-mode coverage, and tests that prove the changed behavior."}
                      </div>
                    </div>

                    <div className="workspace-card-muted rounded-[20px] p-4">
                      <div className="workspace-label">Accepted context</div>
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        <span className="workspace-chip text-[10px]">{selectedPath ? fileLabel(selectedPath) : "No file selected"}</span>
                        <span className="workspace-chip text-[10px]">{previewReady ? "Preview ready" : "Preview pending"}</span>
                        <span className="workspace-chip text-[10px]">{hasChecksRun ? "Checks recorded" : "Checks not run"}</span>
                      </div>
                    </div>
                  </div>

                  <div className="border-t border-[rgba(154,167,255,0.12)] p-3">
                    <div className="workspace-card rounded-[22px] p-3">
                      <textarea
                        className="min-h-[104px] w-full resize-none bg-transparent px-2 py-2 text-sm text-slate-100 outline-none"
                        onChange={(event) => setAssistantDraft(event.target.value)}
                        placeholder="Ask the assistant..."
                        value={assistantDraft}
                      />
                      <div className="flex items-center justify-between border-t border-white/10 px-2 pt-3 text-[11px] text-slate-500">
                        <span>{assistantMessages.filter((message) => message.role === "me").length} prompts · tracked</span>
                        <button
                          className="rounded-[16px] border border-fuchsia-300/24 bg-[linear-gradient(135deg,#ec5bff,#b84eff)] px-4 py-2 text-xs font-semibold text-white shadow-[0_16px_36px_rgba(184,78,255,0.24)] transition hover:-translate-y-0.5 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                          disabled={busyAction !== null || !ready || !assistantDraft.trim()}
                          onClick={() => void sendAssistantPrompt()}
                          type="button"
                        >
                          {busyAction === "assistant" ? "Applying..." : "Send"}
                        </button>
                      </div>
                    </div>
                  </div>
                </>
              ) : previewEnabled ? (
                <div className="workspace-scrollbar min-h-0 flex-1 overflow-y-auto p-3">
                  <div className="workspace-card rounded-[22px] p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="workspace-label">Live project preview</div>
                        <div className="mt-1.5 flex items-center gap-2">
                          <strong className="text-xs font-medium text-slate-100" data-testid="preview-state">
                            {preview?.status ?? "not_started"}
                          </strong>
                          <span className="text-[11px] text-slate-500">{preview?.status === "ready" ? `Ready at ${previewReadyLabel}` : "Compile when you want to render the current draft."}</span>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button
                          className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[11px] font-medium text-slate-200 transition hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-50"
                          data-testid="restart-preview-button"
                          disabled={busyAction !== null || !ready}
                          onClick={() => void recompilePreview()}
                          type="button"
                        >
                          {busyAction === "preview" ? "Refreshing..." : preview?.status === "ready" ? "Refresh preview" : "Open preview"}
                        </button>
                        <button
                          className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-[11px] font-medium text-slate-200 transition hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-50"
                          data-testid="stop-preview-button"
                          disabled={busyAction !== null || preview?.status !== "ready"}
                          onClick={() => void stopPreview()}
                          type="button"
                        >
                          {busyAction === "preview-stop" ? "Stopping..." : "Stop"}
                        </button>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                      {[
                        ["full", "Full"],
                        ["tablet", "Tablet"],
                        ["mobile", "Mobile"],
                      ].map(([value, label]) => (
                        <button
                          className={cn(
                            "rounded-full border px-2.5 py-1 text-[10px] font-medium transition",
                            previewViewport === value ? "border-indigo-200/30 bg-white text-slate-900" : "border-white/10 bg-white/[0.04] text-slate-400 hover:text-slate-200",
                          )}
                          key={value}
                          onClick={() => setPreviewViewport(value as "full" | "tablet" | "mobile")}
                          type="button"
                        >
                          {label}
                        </button>
                      ))}
                      {previewNeedsRecompile ? (
                        <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2.5 py-0.5 text-[10px] font-medium text-amber-300">
                          Draft changed
                        </span>
                      ) : null}
                    </div>
                    {preview?.error ? (
                      <div className="mt-3 rounded-lg border border-rose-500/20 bg-rose-500/10 p-3 text-xs text-rose-200">
                        <p>{preview.error}</p>
                        {preview.log_path ? <p className="mt-2 text-rose-300/80">Preview log: {preview.log_path}</p> : null}
                      </div>
                    ) : null}
                    {previewFrameHref && preview?.status === "ready" ? (
                      <div className="workspace-scrollbar mt-3 overflow-auto rounded-[18px] border border-white/10 bg-[#090c13] p-2" data-testid="preview-frame-container">
                        <div className={cn("mx-auto w-full overflow-hidden rounded-xl border border-white/10 bg-white shadow-[0_20px_60px_rgba(15,23,42,0.35)]", previewViewportClass)}>
                          <iframe
                            className="h-[620px] w-full bg-white"
                            data-testid="candidate-preview-iframe"
                            src={previewFrameHref}
                            title="Candidate preview"
                          />
                        </div>
                      </div>
                    ) : (
                      <div className="mt-3 grid h-[620px] place-items-center rounded-[18px] border border-dashed border-white/10 bg-[#090c13] p-4 text-center text-xs text-slate-500">
                        <div className="max-w-sm space-y-3">
                          <div className="text-base font-medium text-slate-200">No compiled preview yet</div>
                          <p>Open preview to render the project here, then refresh whenever the saved draft changes.</p>
                        </div>
                      </div>
                    )}
                    {previewFrameHref ? (
                      <a
                        className="mt-3 inline-flex items-center justify-center rounded-full border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-medium text-slate-200 transition hover:bg-white/[0.08]"
                        href={previewFrameHref}
                        rel="noreferrer"
                        target="_blank"
                      >
                        Open in full tab
                      </a>
                    ) : null}
                  </div>
                </div>
              ) : (
                <div className="grid min-h-0 flex-1 place-items-center p-6 text-center text-sm text-slate-500">Preview is not enabled for this project.</div>
              )}
            </aside>
            ) : null}
          </div>
        )}
      </section>
    </main>
  );
}
