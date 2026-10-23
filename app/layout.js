import './globals.css';
import { Inter } from 'next/font/google';

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-sans',
});

export const metadata = {
  metadataBase: new URL(process.env.PUBLIC_BASE_URL || process.env.RENDER_EXTERNAL_URL || 'http://localhost:3000'),
  title: {
    default: 'Clipper Factory',
    template: '%s · Clipper Factory',
  },
  description: 'Turn one YouTube link into ten vertical shorts, scheduled and auto-posted.',
  icons: {
    icon: [
      { url: '/assets/logos/icon-1024.png', type: 'image/png', sizes: '1024x1024' },
      { url: '/favicon.ico', sizes: 'any' },
    ],
    apple: '/assets/logos/icon-1024.png',
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={inter.variable}>
      <body>{children}</body>
    </html>
  );
}
