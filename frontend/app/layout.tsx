import { Sidebar } from '@/components/Sidebar';

export const metadata = {
    title: 'Finance API',
    description: 'OpenClaw Finance Dashboard',
};

export default function RootLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <html lang="zh-CN">
            <body className="min-h-screen">
                <Sidebar />
                <main className="md:ml-64 min-h-screen">
                    {children}
                </main>
            </body>
        </html>
    );
}
