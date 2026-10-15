import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="en">
      <body className="bg-paper text-ink antialiased">{children}</body>
    </html>
  );
}
