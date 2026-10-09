import type {Metadata} from 'next';
import './globals.css';
export const metadata: Metadata = {title: 'Agent Factory · Operations, engineered', description: 'Build, evaluate, improve and deploy specialized business agents.'};
export default function RootLayout({children}: {children: React.ReactNode}) {return <html lang="en"><body>{children}</body></html>;}
