import { BookOpen } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { GlossaryTopic } from "../types";

const cache = new Map<string, GlossaryTopic>();

/** Inline glossary link with a definition popover, so users can learn without leaving the page. */
export function GlossaryTerm({ slug, children }: { slug: string; children: ReactNode }) {
  const [topic, setTopic] = useState<GlossaryTopic | null>(cache.get(slug) ?? null);
  const [open, setOpen] = useState(false);
  const show = () => {
    setOpen(true);
    if (!cache.has(slug)) api.glossaryTopic(slug).then((t) => { cache.set(slug, t); setTopic(t); }, () => undefined);
  };
  return <span className="relative inline-block" onMouseEnter={show} onMouseLeave={() => setOpen(false)}>
    <button type="button" onFocus={show} onBlur={() => setOpen(false)} aria-describedby={`gloss-${slug}`}
      className="inline-flex items-center gap-1 border-b border-dotted border-cyan text-left hover:text-cyan">
      {children}<BookOpen className="h-3 w-3 text-cyan" aria-hidden />
    </button>
    {open && <span id={`gloss-${slug}`} role="tooltip"
      className="absolute left-0 top-full z-30 mt-1 block w-80 rounded-md border border-slate-200 bg-white p-3 text-sm font-normal text-ink shadow-lg">
      {topic ? <>
        <span className="block font-semibold text-navy">{topic.term}</span>
        <span className="mt-1 block">{topic.definition}</span>
        <Link to={`/learn#${slug}`} className="mt-2 block text-cyan hover:underline">Open in Knowledge Hub →</Link>
      </> : "Loading definition…"}
    </span>}
  </span>;
}
