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
      <div className="flex flex-wrap items-center gap-1 text-xs text-gray-500">
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

      <div className="max-h-48 space-y-1 overflow-y-auto rounded border border-gray-200 dark:border-gray-800 p-2">
        {isEmpty && <p className="px-2 py-1 text-xs text-gray-500">pasta vazia</p>}
        {dirNames.map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => setCrumbs([...crumbs, d])}
            className="block w-full rounded px-2 py-1 text-left text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
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
              className={`block w-full rounded px-2 py-1 text-left text-sm ${
                selected
                  ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900"
                  : "text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
              }`}
            >
              🎵 {f}
            </button>
          );
        })}
      </div>

      {value && <p className="text-xs text-gray-500">selecionado: {value}</p>}
    </div>
  );
}
