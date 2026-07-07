"use client";

import { useEffect, useState } from "react";
import type { Voice } from "@/app/api/catalog/route";

export interface Catalog {
  ads: string[];
  experts: string[];
  voices: Voice[];
  ad_files: Record<string, string[]>;
  updated_at: string | null;
}

export function useCatalog(): Catalog {
  const [catalog, setCatalog] = useState<Catalog>({
    ads: [],
    experts: [],
    voices: [],
    ad_files: {},
    updated_at: null,
  });

  useEffect(() => {
    fetch("/api/catalog")
      .then((r) => r.json())
      .then(setCatalog)
      .catch(() => {});
  }, []);

  return catalog;
}
