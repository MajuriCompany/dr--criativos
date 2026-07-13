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

      <div className="max-h-40 space-y-1 overflow-y-auto rounded border border-gray-200 dark:border-gray-800 p-2">
        {dirNames.length === 0 && <p className="px-2 py-1 text-xs text-gray-500">sem subpastas aqui</p>}
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
          className="w-full rounded border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100"
        />
        <button
          type="button"
          onClick={createAndEnter}
          disabled={!newName.trim()}
          className="whitespace-nowrap rounded border border-gray-300 dark:border-gray-700 px-2 text-xs text-gray-600 dark:text-gray-400 disabled:opacity-50"
        >
          criar / entrar
        </button>
      </div>

      <button
        type="button"
        onClick={() => onChange(currentPath)}
        className={`w-full rounded px-2 py-1 text-left text-sm ${
          currentPath === value
            ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900"
            : "border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
        }`}
      >
        usar esta pasta{currentPath ? `: ${currentPath}` : " (raiz do anúncio)"}
      </button>

      {value && <p className="text-xs text-gray-500">selecionado: {value || "raiz do anúncio"}</p>}
    </div>
  );
}
