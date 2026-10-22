import './globals.css';

export const metadata = {
  title: 'African Clipper Factory',
  description: 'Turn African tales into scheduled vertical shorts.',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
