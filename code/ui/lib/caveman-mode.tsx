"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

const STORAGE_KEY = "caveman-mode";

type CavemanModeContextValue = {
  isCaveman: boolean;
  toggle: () => void;
};

const CavemanModeContext = createContext<CavemanModeContextValue>({
  isCaveman: false,
  toggle: () => {},
});

export function CavemanModeProvider({ children }: { children: React.ReactNode }) {
  const [isCaveman, setIsCaveman] = useState(false);

  // Hydrate from localStorage after mount (avoids SSR mismatch)
  useEffect(() => {
    setIsCaveman(localStorage.getItem(STORAGE_KEY) === "1");
  }, []);

  const toggle = useCallback(() => {
    setIsCaveman((prev) => {
      const next = !prev;
      localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      return next;
    });
  }, []);

  return (
    <CavemanModeContext.Provider value={{ isCaveman, toggle }}>
      {children}
    </CavemanModeContext.Provider>
  );
}

export function useCavemanMode() {
  return useContext(CavemanModeContext);
}
