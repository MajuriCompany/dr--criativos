"use client";

import { useEffect, useState } from "react";
import type { AudioTreeNode } from "@/lib/useCatalog";

const EMPTY_NODE: AudioTreeNode = { files: [], dirs: {} };

export default function AudioFilePicker({
  tree,
  value,
  onChange,
}: {
  tree: AudioTreeNode;
  value: string;
  onChange: (path: string) => void;
}) {
  const [crumbs, setCrumbs] = useState<string[]>([]);

  // Ad folder changed underneath us (different tree object) — back to root.
  useEffect(() => {
    setCrumbs([]);
  }, [tree]);

  let node: AudioTreeNode = tree ?? EMPTY_NODE;
  for (const c of crumbs) {
    node = node?.dirs?.[c] ?? EMPTY_NODE;
  }

  const dirNames = Object.keys(node.dirs).sort();
  const fileNames = [...node.files].sort();
  const isEmpty = dirNames.length === 0 && fileNames.length === 0;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1 text-xs text-blue-900/50 dark:text-blue-300/50">
        <button type="button" onClick={() => setCrumbs([])} className="underline">
          raiz
        </button>
        {crumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-1">
            <span>/</span>
            <button type="button" onClick={() => setCrumbs(crumbs.slice(0, i + 1))} className="underline">
              {c}
            </button>
          </span>
        ))}
      </div>

      <div className="max-h-48 space-y-1 overflow-y-auto rounded-lg border border-blue-100 dark:border-blue-900/60 p-2">
        {isEmpty && <p className="px-2 py-1 text-xs text-blue-900/50 dark:text-blue-300/50">pasta vazia</p>}
        {dirNames.map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => setCrumbs([...crumbs, d])}
            className="block w-full rounded-lg px-2 py-1 text-left text-sm text-blue-950/80 dark:text-blue-100/80 hover:bg-blue-50 dark:hover:bg-blue-900/40"
          >
            📁 {d}
          </button>
        ))}
        {fileNames.map((f) => {
          const fullPath = [...crumbs, f].join("/");
          const selected = fullPath === value;
          return (
            <button
              key={f}
              type="button"
              onClick={() => onChange(fullPath)}
              className={`block w-full rounded-lg px-2 py-1 text-left text-sm ${
                selected
                  ? "bg-blue-600 text-white dark:bg-blue-500"
                  : "text-blue-950/80 dark:text-blue-100/80 hover:bg-blue-50 dark:hover:bg-blue-900/40"
              }`}
            >
              🎵 {f}
            </button>
          );
        })}
      </div>

      {value && <p className="text-xs text-blue-900/50 dark:text-blue-300/50">selecionado: {value}</p>}
    </div>
  );
}
