import type { Metadata } from "next";
import { Inter, Cinzel } from "next/font/google";
import "./globals.css";
import AuthGuard from "@/components/AuthGuard";
import ThemeProvider from "@/components/ThemeProvider";
import { themeInitializationScript } from "@/lib/theme";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
});

const cinzel = Cinzel({
  variable: "--font-cinzel",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Kuldeep - AI Manufacturing Assistant",
  description: "Your AI assistant for manufacturing processes, manuals, and SOPs.",
  icons: { icon: "/icon.png" },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitializationScript }} />
      </head>
      <body
        className={`${inter.variable} ${cinzel.variable} antialiased`}
        style={{ fontFamily: "var(--font-inter), sans-serif" }}
      >
        <ThemeProvider>
          <AuthGuard>{children}</AuthGuard>
        </ThemeProvider>
      </body>
    </html>
  );
}
