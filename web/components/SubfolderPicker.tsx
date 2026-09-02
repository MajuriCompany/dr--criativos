"use client";

import { useEffect, useState } from "react";
import type { AudioTreeNode } from "@/lib/useCatalog";

const EMPTY_NODE: AudioTreeNode = { files: [], dirs: {} };

export default function SubfolderPicker({
  tree,
  value,
  onChange,
}: {
  tree: AudioTreeNode;
  value: string;
  onChange: (path: string) => void;
}) {
  const [crumbs, setCrumbs] = useState<string[]>([]);
  const [newName, setNewName] = useState("");

  // Ad folder changed underneath us (different tree object) — back to root.
  useEffect(() => {
    setCrumbs([]);
  }, [tree]);

  let node: AudioTreeNode = tree ?? EMPTY_NODE;
  for (const c of crumbs) {
    node = node?.dirs?.[c] ?? EMPTY_NODE;
  }

  const dirNames = Object.keys(node.dirs).sort();
  const currentPath = crumbs.join("/");

  function createAndEnter() {
    const name = newName.trim();
    if (!name) return;
    setCrumbs([...crumbs, name]);
    setNewName("");
  }

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

      <div className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-blue-100 dark:border-blue-900/60 p-2">
        {dirNames.length === 0 && <p className="px-2 py-1 text-xs text-blue-900/50 dark:text-blue-300/50">sem subpastas aqui</p>}
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
      </div>

      <div className="flex gap-2">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              createAndEnter();
            }
          }}
          placeholder="nova subpasta aqui dentro..."
          className="w-full rounded-lg border border-blue-200 dark:border-blue-900 bg-white dark:bg-slate-800 px-3 py-2 text-sm text-blue-950 dark:text-blue-50 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-500/15"
        />
        <button
          type="button"
          onClick={createAndEnter}
          disabled={!newName.trim()}
          className="whitespace-nowrap rounded-lg border border-blue-200 dark:border-blue-900 px-2 text-xs text-blue-900/60 dark:text-blue-300/60 transition hover:bg-blue-50 dark:hover:bg-blue-900/40 disabled:opacity-50 disabled:hover:bg-transparent"
        >
          criar / entrar
        </button>
      </div>

      <button
        type="button"
        onClick={() => onChange(currentPath)}
        className={`w-full rounded-lg px-2 py-1 text-left text-sm ${
          currentPath === value
            ? "bg-blue-600 text-white dark:bg-blue-500"
            : "border border-blue-200 dark:border-blue-900 text-blue-950/80 dark:text-blue-100/80 hover:bg-blue-50 dark:hover:bg-blue-900/40"
        }`}
      >
        usar esta pasta{currentPath ? `: ${currentPath}` : " (raiz do anúncio)"}
      </button>

      {value && <p className="text-xs text-blue-900/50 dark:text-blue-300/50">selecionado: {value || "raiz do anúncio"}</p>}
    </div>
  );
}
