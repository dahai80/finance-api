"use client";

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

const navItems = [
    { href: '/', label: 'Dashboard', icon: '📊' },
    { href: '/ipo/', label: 'IPO', icon: '📈' },
    { href: '/industry/', label: 'Industry', icon: '🏭' },
    { href: '/backtest/', label: 'Backtest', icon: '🔄' },
];

export function Sidebar() {
    const [mobileOpen, setMobileOpen] = useState(false);
    const pathname = usePathname();

    return (
        <>
            {/* Mobile hamburger */}
            <button
                className="md:hidden fixed top-4 left-4 z-50 p-2 bg-white rounded shadow"
                onClick={() => setMobileOpen(!mobileOpen)}
            >
                ☰
            </button>

            {/* Sidebar */}
            <aside
                className={`fixed inset-y-0 left-0 z-40 w-64 bg-slate-900 text-white transform transition-transform duration-200
                ${mobileOpen ? 'translate-x-0' : '-translate-x-full'}
                md:translate-x-0
                `}
            >
                <div className="p-6">
                    <h1 className="text-xl font-bold mb-8">Finance API</h1>
                    <nav className="space-y-2">
                        {navItems.map(item => (
                            <Link
                                key={item.href}
                                href={item.href}
                                className={`
                  flex items-center gap-3 px-4 py-3 rounded-lg transition-colors
                  ${pathname === item.href ? 'bg-blue-600' : 'hover:bg-slate-800'}
                `}
                                onClick={() => setMobileOpen(false)}
                            >
                                <span>{item.icon}</span>
                                <span>{item.label}</span>
                            </Link>
                        ))}
                    </nav>
                </div>
            </aside>

            {/* Overlay for mobile */}
            {mobileOpen && (
                <div
                    className="fixed inset-0 bg-black/50 z-30 md:hidden"
                    onClick={() => setMobileOpen(false)}
                />
            )}
        </>
    );
}
