import type { Metadata } from 'next';
import './globals.css';
import './components.css';

export const metadata: Metadata = {
  title: 'Digital Witness | Video evidence workspace',
  description: 'Search CCTV recordings and review timestamped evidence.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
