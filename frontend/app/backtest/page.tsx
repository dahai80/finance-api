"use client";

import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, Legend } from 'recharts';
import { getBacktestAccuracy, BacktestAccuracy } from '@/lib/api';

export default function BacktestPage() {
    const [data, setData] = useState<BacktestAccuracy[]>([]);
    const [days, setDays] = useState(30);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        async function fetchData() {
            try {
                const res = await getBacktestAccuracy(days);
                setData(res);
            } catch (e) {
                console.error(e);
            } finally {
                setLoading(false);
            }
        }
        fetchData();
    }, [days]);

    if (loading) return <div className="p-8">Loading...</div>;

    const accuracyData = data.map(d => ({
        date: d.date,
        accuracy: d.accuracy,
        correct: d.correct,
        total: d.total_predictions,
    }));

    const conversionData = data.map(d => ({
        date: d.date,
        conversion: d.total_predictions > 0 ? Math.round((d.correct / d.total_predictions) * 100) : 0,
    }));

    return (
        <div className="p-8">
            <div className="flex justify-between items-center mb-6">
                <h1 className="text-2xl font-bold">Backtest 回测</h1>
                <div className="flex items-center gap-2">
                    <label className="text-sm text-gray-600">Days:</label>
                    <select
                        value={days}
                        onChange={e => setDays(Number(e.target.value))}
                        className="px-3 py-2 border rounded-lg"
                    >
                        <option value={7}>7</option>
                        <option value={30}>30</option>
                        <option value={90}>90</option>
                    </select>
                </div>
            </div>

            {/* Stats Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div className="bg-white rounded-lg shadow p-6">
                    <div className="text-sm text-gray-500">Average Accuracy</div>
                    <div className="text-3xl font-bold text-blue-600">
                        {data.length > 0 ? (data.reduce((a, b) => a + b.accuracy, 0) / data.length).toFixed(1) : 0}%
                    </div>
                </div>
                <div className="bg-white rounded-lg shadow p-6">
                    <div className="text-sm text-gray-500">Total Predictions</div>
                    <div className="text-3xl font-bold text-green-600">
                        {data.reduce((a, b) => a + b.total_predictions, 0)}
                    </div>
                </div>
                <div className="bg-white rounded-lg shadow p-6">
                    <div className="text-sm text-gray-500">Total Correct</div>
                    <div className="text-3xl font-bold text-emerald-600">
                        {data.reduce((a, b) => a + b.correct, 0)}
                    </div>
                </div>
            </div>

            {/* Accuracy Chart */}
            <div className="bg-white rounded-lg shadow p-6 mb-6">
                <h2 className="text-lg font-semibold mb-4">准确率曲线</h2>
                <div className="w-full h-80">
                    <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={accuracyData}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="date" />
                            <YAxis domain={[0, 100]} />
                            <Tooltip />
                            <Legend />
                            <Line type="monotone" dataKey="accuracy" stroke="#2563eb" name="Accuracy (%)" />
                        </LineChart>
                    </ResponsiveContainer>
                </div>
            </div>

            {/* Conversion Chart */}
            <div className="bg-white rounded-lg shadow p-6">
                <h2 className="text-lg font-semibold mb-4">转化率图</h2>
                <div className="w-full h-80">
                    <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={conversionData}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="date" />
                            <YAxis />
                            <Tooltip />
                            <Legend />
                            <Bar dataKey="conversion" fill="#3b82f6" name="Conversion Rate (%)" />
                        </BarChart>
                    </ResponsiveContainer>
                </div>
            </div>
        </div>
    );
}
