import { Suspense } from "react";

import HowTo from "@/mono/pages/HowTo";

// HowTo reads URL params (useSearchParams) for article/locale/return deep-linking.
// Since Next 15, a component calling useSearchParams must sit under a Suspense
// boundary for the route shell to be statically prerendered — wrap it here.
export default function HowToPage() {
  return (
    <Suspense>
      <HowTo />
    </Suspense>
  );
}
