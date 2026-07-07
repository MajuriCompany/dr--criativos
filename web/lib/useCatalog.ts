"use client";

import { useCallback, useEffect, useState } from "react";
import type { Voice } from "@/app/api/catalog/route";

export interface AudioTreeNode {
  files: string[];
  dirs: Record<string, AudioTreeNode>;
}

export interface Catalog {
  ads: string[];
  experts: string[];
  voices: Voice[];
  ad_tree: Record<string, AudioTreeNode>;
  updated_at: string | null;
}

const EMPTY: Catalog = {
  ads: [],
  experts: [],
  voices: [],
  ad_tree: {},
  updated_at: null,
};

export interface UseCatalogResult extends Catalog {
  refreshing: boolean;
  refresh: () => Promise<void>;
}

export function useCatalog(): UseCatalogResult {
  const [catalog, setCatalog] = useState<Catalog>(EMPTY);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(() => {
    return fetch("/api/catalog")
      .then((r) => r.json())
      .then(setCatalog)
      .catch(() => {});
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await fetch("/api/catalog/refresh", { method: "POST" });
      // Worker polls every ~10s; give it a moment to honor the request
      // before re-fetching, instead of waiting for the old 60s auto-cycle.
      await new Promise((r) => setTimeout(r, 12000));
      await load();
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  return { ...catalog, refreshing, refresh };
}
