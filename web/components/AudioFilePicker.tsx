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

  // One column per depth: nodes[0] is the root's own contents, nodes[1] is
  // whatever crumbs[0] contains, etc. Clicking a folder opens the next
  // column right beside it instead of replacing the list in place, so the
  // whole path stays visible and it's obvious a click just drilled down
  // (folders) vs. actually picked something (files).
  const nodes: AudioTreeNode[] = [tree ?? EMPTY_NODE];
  for (const c of crumbs) {
    nodes.push(nodes[nodes.length - 1]?.dirs?.[c] ?? EMPTY_NODE);
  }

  function enterAt(depth: number, name: string) {
    setCrumbs([...crumbs.slice(0, depth), name]);
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-0 overflow-x-auto rounded-lg border border-blue-100 dark:border-blue-900/60">
        {nodes.map((node, i) => {
          const dirNames = Object.keys(node.dirs).sort();
          const fileNames = [...node.files].sort();
          const activeChild = crumbs[i];
          const isEmpty = dirNames.length === 0 && fileNames.length === 0;
          return (
            <div
              key={i}
              className={`max-h-48 w-44 shrink-0 space-y-1 overflow-y-auto p-2 ${
                i > 0 ? "border-l border-blue-100 dark:border-blue-900/60" : ""
              }`}
            >
              <p className="px-1 pb-1 text-[10px] font-medium uppercase tracking-wide text-blue-900/40 dark:text-blue-300/40">
                {i === 0 ? "raiz" : crumbs[i - 1]}
              </p>
              {isEmpty && <p className="px-1 py-1 text-xs text-blue-900/40 dark:text-blue-300/40">vazia</p>}
              {dirNames.map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => enterAt(i, d)}
                  title={d}
                  className={`block w-full truncate rounded-lg px-2 py-1 text-left text-sm transition ${
                    activeChild === d
                      ? "bg-blue-100 dark:bg-blue-900/60 text-blue-900 dark:text-blue-100"
                      : "text-blue-950/80 dark:text-blue-100/80 hover:bg-blue-50 dark:hover:bg-blue-900/40"
                  }`}
                >
                  📁 {d}
                </button>
              ))}
              {fileNames.map((f) => {
                const fullPath = [...crumbs.slice(0, i), f].join("/");
                const selected = fullPath === value;
                return (
                  <button
                    key={f}
                    type="button"
                    onClick={() => onChange(fullPath)}
                    title={f}
                    className={`block w-full truncate rounded-lg px-2 py-1 text-left text-sm transition ${
                      selected
                        ? "bg-blue-600 text-white"
                        : "text-blue-950/80 dark:text-blue-100/80 hover:bg-blue-50 dark:hover:bg-blue-900/40"
                    }`}
                  >
                    🎵 {f}
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>

      {value && <p className="text-xs text-blue-900/50 dark:text-blue-300/50">selecionado: {value}</p>}
    </div>
  );
}
