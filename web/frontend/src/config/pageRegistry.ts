// @ts-ignore — resolved by Vite alias
import { pages as projectPages } from "@project/pages";
import type { PageDefinition } from "../types/pages";

export function getPages(): PageDefinition[] {
  return [...projectPages]
    .filter((p: PageDefinition) => p.enabled !== false)
    .sort((a: PageDefinition, b: PageDefinition) => (a.order ?? 50) - (b.order ?? 50));
}
