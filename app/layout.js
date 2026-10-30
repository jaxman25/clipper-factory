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
      { url: '/logo.png', type: 'image/png', sizes: '1024x1024' },
      { url: '/favicon.ico', sizes: 'any' },
    ],
    apple: '/logo.png',
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <body>
        {/* Runs before the rest of the body paints: the stored choice wins,
            otherwise the system preference. globals.css defaults to the dark
            palette, so even a blocked script renders a sane theme. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('theme');if(t!=='dark'&&t!=='light'){t=window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';}document.documentElement.dataset.theme=t;}catch(e){document.documentElement.dataset.theme='dark';}})();`,
          }}
        />
        {children}
      </body>
    </html>
  );
}
