'use client';

import { useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { TrendingUp, DollarSign, Eye } from 'lucide-react';
import { cn } from '@/lib/cn';

function fmt(n) {
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M';
  if (Math.abs(n) >= 1_000) return (n / 1_000).toFixed(1) + 'k';
  return String(n);
}

export default function AnalyticsSummary({ analytics }) {
  const points = useMemo(() => {
    if (!Array.isArray(analytics?.points) || analytics.points.length === 0) return [];
    const points = analytics.points
      .filter((p) => Number.isFinite(Number(p.views)))
      .map((p) => ({
        date: p.date || p.label || '',
        views: Number(p.views),
        earnings: (Number(p.views) / 1000) * 0.5,
      }));
    if (points.length < 2) return points.slice(0, 1);
    return points;
  }, [analytics?.points]);

  const totals = useMemo(() => {
    let views = 0;
    for (const p of points) views += p.views;
    return { views, earnings: points.length ? (views / 1000) * 0.5 : 0 };
  }, [points]);

  if (!points.length) {
    return (
      <div className="card p-5">
        <p className="text-[11px] text-subtle">No analytics data yet. Post clips and they will populate here.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="card p-4">
          <div className="flex items-center justify-between">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-subtle">Total views</p>
            {Eye && <Eye className="h-4 w-4 text-subtle/80" />}
          </div>
          <p className="mt-3 text-2xl font-semibold tracking-tight">{fmt(totals.views)}</p>
          <p className="mt-1 text-[11px] text-subtle">Across all posted clips</p>
        </div>

        <div className="card p-4">
          <div className="flex items-center justify-between">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-subtle">Estimated earnings</p>
            <DollarSign className="h-4 w-4 text-subtle/80" />
          </div>
          <p className="mt-3 text-2xl font-semibold tracking-tight text-brand">${totals.earnings.toFixed(2)}</p>
          <p className="mt-1 text-[11px] text-subtle">
            {(totals.views / 1000).toFixed(1)}k views · ${(totals.earnings / (totals.views / 1000 || 1)).toFixed(2)}/k
          </p>
        </div>
      </div>

      <section className="card p-4">
        <div className="flex items-center justify-between">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold tracking-tight">Views over time</h3>
            <p className="mt-1 text-xs text-muted">Daily views from posted clips, last 30 days.</p>
          </div>
          <div className="flex items-center gap-2 shrink-0 text-[11px] text-subtle">
            <TrendingUp className="h-3.5 w-3.5 text-brand" />
            Estimated earnings: ${totals.earnings.toFixed(2)}
          </div>
        </div>

        <div className="mt-4 h-[260px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--line) / 0.4)" />
              <XAxis
                dataKey="date"
                tick={{ fill: 'hsl(var(--fg) / 0.6)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: 'hsl(var(--fg) / 0.6)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={fmt}
              />
              <Tooltip
                contentStyle={{
                  background: 'hsl(var(--surface))',
                  border: '1px solid hsl(var(--line))',
                  borderRadius: '10px',
                  color: 'hsl(var(--fg))',
                  fontSize: '12px',
                }}
                formatter={(value, name) => {
                  const row = {
                    views: fmt(value),
                    earnings: `$${(value / 1000) * 0.5}.toFixed(2)`,
                  };
                  return [row[name === 'earnings' ? 'earnings' : 'views'], name];
                }}
              />
              <Line
                type="monotone"
                dataKey="views"
                stroke="hsl(var(--brand-hsl))"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: 'hsl(var(--brand-hsl))' }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>
    </div>
  );
}
