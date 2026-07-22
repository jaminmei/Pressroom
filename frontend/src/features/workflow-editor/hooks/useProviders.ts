import { useCallback, useEffect, useRef, useState } from "react";

import { listProviders } from "@/services/providerApi";
import type { Provider } from "@/types/provider";

interface UseProvidersResult {
  providers: Provider[];
  loading: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useProviders(category: string): UseProvidersResult {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  const fetch = useCallback(() => {
    // Cancel any in-flight request
    cancelRef.current?.();
    let cancelled = false;
    cancelRef.current = () => { cancelled = true; };

    setLoading(true);
    setError(null);

    listProviders({ category, enabled_only: true })
      .then((data) => {
        if (!cancelled) {
          setProviders(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err : new Error(String(err)));
          setLoading(false);
        }
      });
  }, [category]);

  useEffect(() => {
    fetch();
    return () => { cancelRef.current?.(); };
  }, [fetch]);

  return { providers, loading, error, refetch: fetch };
}
