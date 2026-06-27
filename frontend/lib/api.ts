const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function fetchApi(path: string, options?: RequestInit) {
    const res = await fetch(`${API_URL}${path}`, {
        ...options,
        headers: {
            'Content-Type': 'application/json',
            ...options?.headers,
        },
    });
    if (!res.ok) {
        const text = await res.text();
        throw new Error(`API error ${res.status}: ${text}`);
    }
    return res.json();
}

// ── Types ───────────────────────────────────────────────────────────

export interface IpoItem {
    stock_code: string;
    stock_name: string;
    ipo_date: string;
    fundamental_metrics: Record<string, any>;
    valuation_score: number;
    recommendation_level: string;
    status: string;
    ai_generated_script: string | null;
}

export interface IpoListResponse {
    data: IpoItem[];
    total: number;
    limit: number;
    offset: number;
}

export interface MoneyFlowItem {
    sector: string;
    flow: number;
}

export interface MarketAlertItem {
    stock_code: string;
    stock_name: string;
    ipo_date: string;
    valuation_score: number;
    recommendation_level: string;
    pe: number | null;
    industry_pe: number | null;
    price: number | null;
}

export interface MarketSentiment {
    top_inflow: MoneyFlowItem[];
    top_outflow: MoneyFlowItem[];
    high_score_ipos: MarketAlertItem[];
    market_phase: string;
}

export interface IndustryEvent {
    event_id: number;
    event_title: string;
    industry_tags: string[];
    impact_analysis: string | null;
    related_stock_codes: string[];
    event_time: string | null;
}

export interface BacktestAccuracy {
    date: string;
    total_predictions: number;
    correct: number;
    accuracy: number;
}

// ── API Functions ───────────────────────────────────────────────────

export async function listIpos(params?: { limit?: number; offset?: number; status?: string; min_score?: number; search?: string }) {
    const query = new URLSearchParams();
    if (params?.limit) query.set('limit', String(params.limit));
    if (params?.offset) query.set('offset', String(params.offset));
    if (params?.status) query.set('status', params.status);
    if (params?.min_score !== undefined) query.set('min_score', String(params.min_score));
    if (params?.search) query.set('search', params.search);
    return fetchApi(`/api/ipo?${query.toString()}`) as Promise<IpoListResponse>;
}

export async function syncIpos() {
    return fetchApi('/api/ipo/sync', { method: 'POST' });
}

export async function getMoneyFlow(limit: number = 30) {
    return fetchApi(`/api/market/money-flow?limit=${limit}`) as Promise<MoneyFlowItem[]>;
}

export async function getMarketAlerts(min_score: number = 60, limit: number = 20) {
    return fetchApi(`/api/market/alerts?min_score=${min_score}&limit=${limit}`) as Promise<MarketAlertItem[]>;
}

export async function getMarketSentiment() {
    return fetchApi('/api/market/sentiment') as Promise<MarketSentiment>;
}

export async function getIndustryEvents(limit: number = 20) {
    return fetchApi(`/api/industry/events?limit=${limit}`) as Promise<IndustryEvent[]>;
}

export async function getBacktestAccuracy(days: number = 30) {
    return fetchApi(`/api/backtest/accuracy?days=${days}`) as Promise<BacktestAccuracy[]>;
}
