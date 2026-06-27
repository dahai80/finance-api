"use client";

import { useState, useEffect } from 'react';
import { getIndustryEvents, IndustryEvent } from '@/lib/api';

export default function IndustryPage() {
    const [events, setEvents] = useState<IndustryEvent[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        async function fetchData() {
            try {
                const data = await getIndustryEvents(20);
                setEvents(data);
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
            <h1 className="text-2xl font-bold mb-6">Industry 事件</h1>

            {/* Event Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
                {events.map(evt => (
                    <div key={evt.event_id} className="bg-white rounded-lg shadow p-6 hover:shadow-lg transition-shadow">
                        <h3 className="font-semibold text-lg mb-2">{evt.event_title}</h3>
                        <div className="flex flex-wrap gap-2 mb-3">
                            {evt.industry_tags.map(tag => (
                                <span key={tag} className="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded">{tag}</span>
                            ))}
                        </div>
                        {evt.impact_analysis && (
                            <p className="text-sm text-gray-600 mb-3">{evt.impact_analysis}</p>
                        )}
                        <div className="text-xs text-gray-500">
                            {evt.event_time ? new Date(evt.event_time).toLocaleDateString('zh-CN') : 'N/A'}
                        </div>
                        {evt.related_stock_codes.length > 0 && (
                            <div className="mt-2 text-xs text-gray-500">
                                Stocks: {evt.related_stock_codes.join(', ')}
                            </div>
                        )}
                    </div>
                ))}
            </div>

            {/* Timeline */}
            <h2 className="text-xl font-bold mb-4">事件时间轴</h2>
            <div className="relative">
                {events.map((evt, index) => (
                    <div key={evt.event_id} className="flex gap-4 mb-8 last:mb-0">
                        <div className="flex flex-col items-center">
                            <div className="w-3 h-3 bg-blue-500 rounded-full" />
                            {index < events.length - 1 && (
                                <div className="w-0.5 h-full bg-gray-200 mt-1" />
                            )}
                        </div>
                        <div className="flex-1 pb-4">
                            <div className="text-sm text-gray-500">
                                {evt.event_time ? new Date(evt.event_time).toLocaleDateString('zh-CN') : 'N/A'}
                            </div>
                            <h3 className="font-semibold text-gray-900">{evt.event_title}</h3>
                            {evt.impact_analysis && (
                                <p className="text-sm text-gray-600 mt-1">{evt.impact_analysis}</p>
                            )}
                            {evt.industry_tags.length > 0 && (
                                <div className="flex flex-wrap gap-2 mt-2">
                                    {evt.industry_tags.map(tag => (
                                        <span key={tag} className="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded">{tag}</span>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
