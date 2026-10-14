import type { Metadata } from "next";
import { Source_Serif_4, Public_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const sourceSerif4 = Source_Serif_4({
  subsets: ["latin"],
  variable: "--font-source-serif-4",
  weight: ["400", "600"],
  display: "swap",
});

const publicSans = Public_Sans({
  subsets: ["latin"],
  variable: "--font-public-sans",
  weight: ["400", "500", "600"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  weight: ["400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "ClaimGraph",
  description: "Evidence compiler for MSME payment claims",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${sourceSerif4.variable} ${publicSans.variable} ${jetbrainsMono.variable}`}
    >
      <body className="bg-paper text-ink antialiased">{children}</body>
    </html>
  );
}
