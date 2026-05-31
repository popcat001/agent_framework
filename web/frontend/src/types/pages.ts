import type { ComponentType, ReactNode } from "react";

/**
 * Props passed to a page component. Plain pages ignore them; pages with
 * `ownsSidebar` use them to render chat-identical chrome — their own sidebar
 * on the left with the shared TabBar above the content on the right.
 */
export interface PageChromeProps {
  /** The shared top TabBar element, rendered above the page's content. */
  tabBar?: ReactNode;
  /** Whether the page's own sidebar should be shown (driven by the toggle). */
  sidebarOpen?: boolean;
}

export interface PageDefinition {
  /** Unique tab key, e.g. "reports" */
  id: string;
  /** Display label in the tab bar */
  label: string;
  /** Lucide icon name (string) */
  icon: string;
  /** React component to render */
  component: ComponentType<PageChromeProps>;
  /** Sort order — lower = more left. Chat is always 0. */
  order?: number;
  /** Whether the tab is visible. Defaults to true. */
  enabled?: boolean;
  /**
   * Set when the page renders its own sidebar (with a user-profile footer)
   * like the chat sidebar. When true, Layout gives the page the shared TabBar
   * + sidebarOpen so it can render chat-identical chrome, the sidebar reaches
   * the top, and the top-bar user chip is suppressed (the page's footer shows
   * the user instead). Defaults to false.
   */
  ownsSidebar?: boolean;
}
