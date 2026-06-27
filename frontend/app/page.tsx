"use client";

import { useState, useEffect } from 'react';
import { getMarketAlerts, getMarketSentiment, getMoneyFlow, MoneyFlowItem, MarketAlertItem, MarketSentiment } from '@/lib/api';

export default function DashboardPage() {
    const [moneyFlow, setMoneyFlow] = useState<MoneyFlowItem[]>([]);
    const [alerts, setAlerts] = useState<MarketAlertItem[]>([]);
    const [sentiment, setSentiment] = useState<MarketSentiment | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        async function fetchData() {
            try {
                const [mf, al, se] = await Promise.all([
                    getMoneyFlow(10),
                    getMarketAlerts(60, 20),
                    getMarketSentiment(),
                ]);
                setMoneyFlow(mf);
                setAlerts(al);
                setSentiment(se);
            } catch (e) {
                console.error(e);
            } finally {
                setLoading(false);
            }
        }
        fetchData();
    }, []);

    if (loading) return <div className="p-8">Loading...</div>;

    return (
        <div className="p-8">
            <h1 className="text-2xl font-bold mb-6">Dashboard</h1>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Alerts */}
                <div className="bg-white rounded-lg shadow p-6">
                    <h2 className="text-lg font-semibold mb-4">异动预警</h2>
                    <div className="space-y-3">
                        {alerts.map(a => (
                            <div key={a.stock_code} className="flex justify-between items-center p-3 bg-gray-50 rounded">
                                <div>
                                    <div className="font-medium">{a.stock_name} ({a.stock_code})</div>
                                    <div className="text-sm text-gray-500">Score: {a.valuation_score}</div>
                                </div>
                                <span className={`px-2 py-1 text-xs rounded ${a.valuation_score >= 80 ? 'bg-green-100 text-green-700' : a.valuation_score >= 60 ? 'bg-yellow-100 text-yellow-700' : 'bg-gray-100 text-gray-700'}`}>
                                    {a.recommendation_level}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Money Flow */}
                <div className="bg-white rounded-lg shadow p-6">
                    <h2 className="text-lg font-semibold mb-4">资金流</h2>
                    <div className="space-y-3">
                        {moneyFlow.map(mf => (
                            <div key={mf.sector} className="flex justify-between items-center p-3 bg-gray-50 rounded">
                                <span>{mf.sector}</span>
                                <span className={`font-mono ${mf.flow > 0 ? 'text-green-600' : 'text-red-600'}`}>
                                    {mf.flow > 0 ? '+' : ''}{mf.flow.toFixed(2)}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Sentiment */}
                <div className="bg-white rounded-lg shadow p-6">
                    <h2 className="text-lg font-semibold mb-4">市场情绪</h2>
                    {sentiment && (
                        <div className="space-y-4">
                            <div>
                                <div className="text-sm text-gray-500">Market Phase</div>
                                <div className="text-xl font-bold">{sentiment.market_phase}</div>
                            </div>
                            <div>
                                <div className="text-sm text-gray-500">High Score IPOs</div>
                                <div className="text-2xl font-bold text-blue-600">{sentiment.high_score_ipos.length}</div>
                            </div>
                            <div>
                                <div className="text-sm text-gray-500">Top Inflow</div>
                                <div className="text-sm">{sentiment.top_inflow[0]?.sector || 'N/A'}</div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
