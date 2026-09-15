"use client";

import { PropsWithChildren, useState } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { LocaleProvider } from "@/hooks/useLocale";
import { ToastProvider } from "@/hooks/useToast";

// The console applies its own token layer via the `.adcs`/`.pub` + `.t-mono` root classes
// (see src/theme/mono.css and src/mono/shell/prefs.tsx); standalone pages manage
// their own theme. Only the data layer (TanStack Query) is provided app-wide.
export function Providers({ children }: PropsWithChildren) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  // LocaleProvider + ToastProvider back the data hooks (useSnapshotState, etc.).
  // The Mono shell owns its own prefs/overlays for the UI.
  return (
    <QueryClientProvider client={queryClient}>
      <LocaleProvider>
        <ToastProvider>{children}</ToastProvider>
      </LocaleProvider>
    </QueryClientProvider>
  );
}
