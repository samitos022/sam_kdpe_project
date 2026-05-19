import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// shadcn/ui-style class merger. Install: npm install clsx tailwind-merge
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatPct(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`;
}

export function formatDelta(value: number): string {
  return value.toFixed(2);
}

export const DOMAIN_LABELS: Record<string, string> = {
  aita: "AITA (Reddit)",
  pubmed_ethnobotany: "PubMed Ethnobotany",
};

// Consistent color per entity class name (deterministic hash)
const CLASS_COLORS = [
  "bg-violet-100 text-violet-800 border-violet-200",
  "bg-teal-100 text-teal-800 border-teal-200",
  "bg-amber-100 text-amber-800 border-amber-200",
  "bg-sky-100 text-sky-800 border-sky-200",
  "bg-rose-100 text-rose-800 border-rose-200",
  "bg-emerald-100 text-emerald-800 border-emerald-200",
  "bg-orange-100 text-orange-800 border-orange-200",
  "bg-indigo-100 text-indigo-800 border-indigo-200",
];

export function classColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0;
  return CLASS_COLORS[Math.abs(hash) % CLASS_COLORS.length];
}

// Same but returns a hex color for D3 graph nodes
const HEX_COLORS = [
  "#7c3aed", "#0d9488", "#d97706", "#0284c7",
  "#e11d48", "#059669", "#ea580c", "#4338ca",
];

export function classHex(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0;
  return HEX_COLORS[Math.abs(hash) % HEX_COLORS.length];
}