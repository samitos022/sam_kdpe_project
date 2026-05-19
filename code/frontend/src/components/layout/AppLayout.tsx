import { useState, useRef, useEffect } from "react";

// ─── AppLayout ───────────────────────────────────────────────────────────────

interface AppLayoutProps {
  sidebar: React.ReactNode;
  children: React.ReactNode;
}

export function AppLayout({ sidebar, children }: AppLayoutProps) {
  const [sidebarWidth, setSidebarWidth] = useState(240); // default w-60 = 240px
  const isDraggingRef = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDraggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const newWidth = Math.max(180, Math.min(600, e.clientX - rect.left));
      setSidebarWidth(newWidth);
    };

    const handleMouseUp = () => {
      isDraggingRef.current = false;
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="flex h-screen overflow-hidden bg-zinc-50 dark:bg-zinc-950"
    >
      <aside
        style={{ width: `${sidebarWidth}px` }}
        className="flex flex-col border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900"
      >
        {sidebar}
      </aside>

      {/* Resize handle */}
      <div
        onMouseDown={() => {
          isDraggingRef.current = true;
        }}
        className="group w-1 cursor-col-resize hover:bg-blue-500 hover:w-1.5 active:bg-blue-600 transition-all"
        title="Drag to resize sidebar"
      />

      <main className="flex flex-1 flex-col overflow-hidden">{children}</main>
    </div>
  );
}

