import type { Metadata } from "next";
import { Fira_Code, Fira_Sans } from "next/font/google";
import Sidebar from "@/components/Sidebar";
import "./globals.css";

const firaSans = Fira_Sans({
  variable: "--font-fira-sans",
  weight: ["400", "500", "600", "700"],
  subsets: ["latin"],
});

const firaCode = Fira_Code({
  variable: "--font-fira-code",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Ragnarok Market Intelligence",
  description: "Market intelligence dashboard for the Ragnarok Online catalog scraper.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${firaSans.variable} ${firaCode.variable} h-full antialiased`}
    >
      <body className="min-h-full flex bg-background text-foreground">
        <Sidebar />
        <main className="flex-1 min-w-0 px-4 md:px-6 pt-16 md:pt-6 pb-6">{children}</main>
      </body>
    </html>
  );
}
