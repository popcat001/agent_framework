// Explicit Lucide icon registry.
//
// Icons are referenced by *string name* from runtime config — `agent.yaml`
// `icon:` fields, project sample-question icons, and page-registry tab icons.
// Importing the whole `lucide-react` namespace (`import * as`) to resolve those
// strings defeats tree-shaking and pulls the entire icon set into the bundle
// (~1.3 MB chunk). Instead we register only the icons actually used as named
// imports here, so the bundler keeps just those.
//
// When a new icon name is configured (new agent.yaml icon, new sample
// question, new page tab), add it to this map — otherwise it falls back to the
// caller's default icon.
import {
  ArrowUpRight,
  BarChart3,
  Briefcase,
  DollarSign,
  GitCompare,
  Globe,
  HelpCircle,
  Layers,
  MessageSquare,
  Target,
  TrendingUp,
  Trophy,
  Users,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

const ICONS: Record<string, LucideIcon> = {
  ArrowUpRight,
  BarChart3,
  Briefcase,
  DollarSign,
  GitCompare,
  Globe,
  HelpCircle,
  Layers,
  MessageSquare,
  Target,
  TrendingUp,
  Trophy,
  Users,
  Zap,
};

/** Resolve a Lucide icon by its string name. Returns `undefined` when the name
 *  is missing or unregistered — callers supply their own fallback. */
export function resolveIcon(name: string | null | undefined): LucideIcon | undefined {
  return name ? ICONS[name] : undefined;
}
