import type { Metadata } from "next";
import localFont from "next/font/local";

import { Providers } from "@/components/providers";

import "./globals.css";
import "../theme/mono.css";

// UI font (Tuffy) + NK57 Monospace for identifiers/codes/numerics. Both are public domain and
// vendored in src/fonts (sources and checksums in src/fonts/README.md), so builds fetch no fonts.
const tuffy = localFont({
  variable: "--font-tuffy",
  src: [
    { path: "../fonts/tuffy/Tuffy-Regular.woff2", weight: "400", style: "normal" },
    { path: "../fonts/tuffy/Tuffy-Italic.woff2", weight: "400", style: "italic" },
    { path: "../fonts/tuffy/Tuffy-Bold.woff2", weight: "700", style: "normal" },
    { path: "../fonts/tuffy/Tuffy-BoldItalic.woff2", weight: "700", style: "italic" },
  ],
});

const nk57Mono = localFont({
  variable: "--font-nk57",
  src: [
    { path: "../fonts/nk57-monospace/NK57Monospace-Book.woff2", weight: "400", style: "normal" },
    { path: "../fonts/nk57-monospace/NK57Monospace-BookItalic.woff2", weight: "400", style: "italic" },
    { path: "../fonts/nk57-monospace/NK57Monospace-Regular.woff2", weight: "500", style: "normal" },
    { path: "../fonts/nk57-monospace/NK57Monospace-RegularItalic.woff2", weight: "500", style: "italic" },
    { path: "../fonts/nk57-monospace/NK57Monospace-SemiBold.woff2", weight: "600", style: "normal" },
    { path: "../fonts/nk57-monospace/NK57Monospace-SemiBoldItalic.woff2", weight: "600", style: "italic" },
  ],
  // The generated metric-matched fallback would be Arial (proportional); mono.css falls
  // back to ui-monospace instead.
  adjustFontFallback: false,
});

export const metadata: Metadata = {
  title: "ADCS — Admin console",
  description: "Aspose Developer Context Service — operations console",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${tuffy.variable} ${nk57Mono.variable}`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
