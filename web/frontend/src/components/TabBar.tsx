import { MessageCircle, PanelLeft } from "lucide-react";
import { resolveIcon } from "../config/iconRegistry";
import { getPages } from "../config/pageRegistry";
import { useAuth } from "../contexts/AuthContext";
import type { PageDefinition } from "../types/pages";

interface TabBarProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
}

const extraPages = getPages();

// Build tabs: chat is always first, then project pages
const tabs: { id: string; label: string; icon: React.ComponentType<{ size: number }>; enabled: boolean }[] = [
  { id: "chat", label: "Chat", icon: MessageCircle, enabled: true },
  ...extraPages.map((p: PageDefinition) => ({
    id: p.id,
    label: p.label,
    icon: resolveIcon(p.icon) ?? MessageCircle,
    enabled: p.enabled !== false,
  })),
];

export function TabBar({ activeTab, onTabChange, sidebarOpen, onToggleSidebar }: TabBarProps) {
  const showTabs = tabs.length > 1;
  const { user } = useAuth();
  // Show the user chip in the bar only when no sidebar footer already shows
  // the user. A footer is visible when the sidebar is open and the active tab
  // has one: chat always does, and so does an extra page with `ownsSidebar`.
  // When the sidebar is collapsed the footer is hidden, so the chip returns.
  const activeExtraPage = extraPages.find((p) => p.id === activeTab);
  const userFooterVisible =
    sidebarOpen && (activeTab === "chat" || !!activeExtraPage?.ownsSidebar);
  const showUserInBar = !userFooterVisible;

  // Whether the bar contains anything besides the toggle. When it doesn't
  // (sidebar open, no extra tabs, no user chip), we drop the bottom border
  // and tighten padding so the toggle anchors flush to the top-left corner
  // instead of floating in an otherwise-empty bar.
  const hasOtherContent = showTabs || (showUserInBar && !!user);

  return (
    <div
      className={`flex items-center px-2 ${hasOtherContent ? "py-2 border-b" : "py-1.5"}`}
      style={{ borderColor: "var(--border)" }}
    >
      {/* Left: Sidebar toggle — always visible so the button stays in the
          same position whether the sidebar is open or collapsed. */}
      <div className="flex-1 flex items-center">
        <button
          onClick={onToggleSidebar}
          title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
          aria-label={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
          className="p-2 rounded-lg transition-colors cursor-pointer hover:bg-black/5"
          style={{ color: "var(--text-secondary)" }}
        >
          <PanelLeft size={18} />
        </button>
      </div>

      {/* Center: Tabs */}
      {showTabs && (
        <div
          className="flex gap-1 px-1 py-1 rounded-xl"
          style={{ background: "var(--bg-sidebar)" }}
        >
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => tab.enabled && onTabChange(tab.id)}
                className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-medium transition-all cursor-pointer ${
                  !tab.enabled ? "opacity-40 cursor-not-allowed" : ""
                }`}
                style={{
                  background: isActive ? "var(--bg-input)" : "transparent",
                  color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
                  boxShadow: isActive ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
                }}
                disabled={!tab.enabled}
              >
                <Icon size={14} />
                {tab.label}
              </button>
            );
          })}
        </div>
      )}

      {/* Right: User profile (shown when sidebar is hidden) */}
      <div className="flex-1 flex items-center justify-end">
        {showUserInBar && user && (
          <div className="flex items-center gap-2.5">
            <div className="flex items-center gap-2">
              <div
                className="flex items-center justify-center text-xs font-medium text-white"
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: "50%",
                  background: "var(--accent)",
                }}
              >
                {user.display_name?.[0] || user.email?.[0] || "?"}
              </div>
              <span
                className="text-sm"
                style={{ color: "var(--text-primary)", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
              >
                {user.display_name || user.email?.split("@")[0] || "User"}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export { extraPages };
