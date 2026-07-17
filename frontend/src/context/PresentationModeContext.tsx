import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";

export type ViewMode = "workspace" | "presentation";

interface PresentationModeValue {
  viewMode: ViewMode;
  isPresentation: boolean;
  enterPresentation: () => void;
  exitPresentation: () => void;
  togglePresentation: () => void;
}

const STORAGE_KEY = "socialpilot:view-mode";

const PresentationModeContext = createContext<PresentationModeValue | null>(null);

function initialViewMode(): ViewMode {
  const params = new URLSearchParams(window.location.search);
  if (params.get("mode") === "presentation") return "presentation";
  try {
    return sessionStorage.getItem(STORAGE_KEY) === "presentation"
      ? "presentation"
      : "workspace";
  } catch {
    return "workspace";
  }
}

export function PresentationModeProvider({ children }: { children: ReactNode }) {
  const [viewMode, setViewMode] = useState<ViewMode>(initialViewMode);
  const navigate = useNavigate();

  const applyMode = useCallback(
    (nextMode: ViewMode) => {
      setViewMode(nextMode);
      try {
        sessionStorage.setItem(STORAGE_KEY, nextMode);
      } catch {
        // Presentation mode still works if storage is unavailable.
      }
      const params = new URLSearchParams(
        nextMode === "presentation" ? "mode=presentation" : "",
      );
      navigate(
        {
          pathname: "/",
          search: params.toString() ? `?${params.toString()}` : "",
        },
        { replace: true },
      );
    },
    [navigate],
  );

  const enterPresentation = useCallback(
    () => applyMode("presentation"),
    [applyMode],
  );
  const exitPresentation = useCallback(
    () => applyMode("workspace"),
    [applyMode],
  );
  const togglePresentation = useCallback(
    () => applyMode(viewMode === "presentation" ? "workspace" : "presentation"),
    [applyMode, viewMode],
  );

  useEffect(() => {
    if (viewMode !== "presentation") return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") exitPresentation();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [exitPresentation, viewMode]);

  const value = useMemo(
    () => ({
      viewMode,
      isPresentation: viewMode === "presentation",
      enterPresentation,
      exitPresentation,
      togglePresentation,
    }),
    [enterPresentation, exitPresentation, togglePresentation, viewMode],
  );

  return (
    <PresentationModeContext.Provider value={value}>
      {children}
    </PresentationModeContext.Provider>
  );
}

export function usePresentationMode(): PresentationModeValue {
  const context = useContext(PresentationModeContext);
  if (!context) {
    throw new Error("usePresentationMode must be used inside PresentationModeProvider");
  }
  return context;
}
