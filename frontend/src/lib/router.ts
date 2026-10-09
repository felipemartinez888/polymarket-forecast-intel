import { useEffect, useState } from "react";

// Minimal hash router: works on any static host without rewrite rules.
export function useRoute(): string[] {
  const parse = () => (window.location.hash.replace(/^#\/?/, "") || "overview").split("/").map(decodeURIComponent);
  const [route, setRoute] = useState<string[]>(parse);
  useEffect(() => {
    const on = () => {
      setRoute(parse());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export const href = (...parts: string[]): string => `#/${parts.map(encodeURIComponent).join("/")}`;
