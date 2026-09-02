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

  // One column per depth: nodes[0] is the root's own subfolders, nodes[1]
  // is whatever crumbs[0] contains, etc. — clicking a folder in column i
  // both opens column i+1 AND immediately confirms it as the selection
  // (no separate "usar esta pasta" step to forget).
  const nodes: AudioTreeNode[] = [tree ?? EMPTY_NODE];
  for (const c of crumbs) {
    nodes.push(nodes[nodes.length - 1]?.dirs?.[c] ?? EMPTY_NODE);
  }

  function selectAt(depth: number, name: string) {
    const next = [...crumbs.slice(0, depth), name];
    setCrumbs(next);
    onChange(next.join("/"));
  }

  function selectRoot() {
    setCrumbs([]);
    onChange("");
  }

  function createAndEnter() {
    const name = newName.trim();
    if (!name) return;
    selectAt(crumbs.length, name);
    setNewName("");
  }

  const currentPath = crumbs.join("/");

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={selectRoot}
        className={`rounded-lg px-2 py-1 text-left text-xs transition ${
          value === ""
            ? "bg-blue-600 text-white"
            : "border border-blue-200 dark:border-blue-900 text-blue-900/60 dark:text-blue-300/60 hover:bg-blue-50 dark:hover:bg-blue-900/40"
        }`}
      >
        usar raiz do anúncio
      </button>

      <div className="flex gap-0 overflow-x-auto rounded-lg border border-blue-100 dark:border-blue-900/60">
        {nodes.map((node, i) => {
          const dirNames = Object.keys(node.dirs).sort();
          const activeChild = crumbs[i];
          return (
            <div
              key={i}
              className={`max-h-48 w-40 shrink-0 space-y-1 overflow-y-auto p-2 ${
                i > 0 ? "border-l border-blue-100 dark:border-blue-900/60" : ""
              }`}
            >
              <p className="px-1 pb-1 text-[10px] font-medium uppercase tracking-wide text-blue-900/40 dark:text-blue-300/40">
                {i === 0 ? "raiz" : crumbs[i - 1]}
              </p>
              {dirNames.length === 0 && (
                <p className="px-1 py-1 text-xs text-blue-900/40 dark:text-blue-300/40">sem subpastas</p>
              )}
              {dirNames.map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => selectAt(i, d)}
                  title={d}
                  className={`block w-full truncate rounded-lg px-2 py-1 text-left text-sm transition ${
                    activeChild === d
                      ? "bg-blue-600 text-white"
                      : "text-blue-950/80 dark:text-blue-100/80 hover:bg-blue-50 dark:hover:bg-blue-900/40"
                  }`}
                >
                  📁 {d}
                </button>
              ))}
            </div>
          );
        })}
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
          placeholder={`nova subpasta em "${currentPath || "raiz"}"...`}
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

      <p className="text-xs text-blue-900/50 dark:text-blue-300/50">
        pasta selecionada: <span className="font-medium">{value || "raiz do anúncio"}</span>
      </p>
    </div>
  );
}
