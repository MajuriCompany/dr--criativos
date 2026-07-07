"use client";

import { useEffect, useState } from "react";
import type { Voice } from "@/app/api/catalog/route";

export interface Catalog {
  ads: string[];
  experts: string[];
  voices: Voice[];
  updated_at: string | null;
}

export function useCatalog(): Catalog {
  const [catalog, setCatalog] = useState<Catalog>({
    ads: [],
    experts: [],
    voices: [],
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
