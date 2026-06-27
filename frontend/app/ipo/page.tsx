"use client";

import { useState, useEffect } from 'react';
import { listIpos, syncIpos, IpoItem } from '@/lib/api';
import { RadarChartComponent } from '@/components/RadarChart';

export default function IpoPage() {
    const [ipos, setIpos] = useState<IpoItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState(false);
    const [search, setSearch] = useState('');

    async function fetchIpos() {
        setLoading(true);
        try {
            const res = await listIpos({ limit: 50, search: search || undefined });
            setIpos(res.data);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        fetchIpos();
    }, []);

    async function handleSync() {
        setSyncing(true);
        try {
            await syncIpos();
            await fetchIpos();
        } catch (e) {
            console.error(e);
        } finally {
            setSyncing(false);
        }
    }

    // Build radar data from first IPO with fundamental_metrics
    const firstIpo = ipos[0];
    const radarData = firstIpo
        ? [
              { subject: 'PE', A: firstIpo.fundamental_metrics?.pe || 50, fullMark: 100 },
              { subject: 'ROE', A: firstIpo.fundamental_metrics?.roe || 50, fullMark: 100 },
              { subject: 'Growth', A: firstIpo.fundamental_metrics?.growth || 50, fullMark: 100 },
              { subject: 'Valuation', A: firstIpo.valuation_score, fullMark: 100 },
              { subject: 'Industry', A: firstIpo.fundamental_metrics?.industry_rank || 50, fullMark: 100 },
          ]
        : [];

    return (
        <div className="p-8">
            <div className="flex justify-between items-center mb-6">
                <h1 className="text-2xl font-bold">IPO 工厂</h1>
                <div className="flex gap-3">
                    <input
                        type="text"
                        placeholder="Search..."
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && fetchIpos()}
                        className="px-4 py-2 border rounded-lg"
                    />
                    <button
                        onClick={handleSync}
                        disabled={syncing}
                        className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                    >
                        {syncing ? 'Syncing...' : 'Sync'}
                    </button>
                </div>
            </div>

            {loading ? (
                <div>Loading...</div>
            ) : (
                <>
                    {/* Radar Chart */}
                    {radarData.length > 0 && (
                        <div className="bg-white rounded-lg shadow p-6 mb-6">
                            <h2 className="text-lg font-semibold mb-4">五维雷达图 — {firstIpo.stock_name}</h2>
                            <RadarChartComponent data={radarData} />
                        </div>
                    )}

                    {/* Table */}
                    <div className="bg-white rounded-lg shadow overflow-hidden">
                        <table className="w-full">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Code</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Score</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Recommendation</th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-200">
                                {ipos.map(ipo => (
                                    <tr key={ipo.stock_code} className="hover:bg-gray-50">
                                        <td className="px-6 py-4 whitespace-nowrap font-mono text-sm">{ipo.stock_code}</td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm">{ipo.stock_name}</td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm">{ipo.ipo_date}</td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <span className={`inline-flex px-2 py-1 text-xs rounded ${ipo.valuation_score >= 80 ? 'bg-green-100 text-green-700' : ipo.valuation_score >= 60 ? 'bg-yellow-100 text-yellow-700' : 'bg-gray-100 text-gray-700'}`}>
                                                {ipo.valuation_score}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm">{ipo.recommendation_level}</td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm">{ipo.status}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </>
            )}
        </div>
    );
}
