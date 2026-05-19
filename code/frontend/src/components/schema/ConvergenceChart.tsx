import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { Card } from "../ui/Card";


// ─── ConvergenceChart ────────────────────────────────────────────────────────

interface ConvergenceChartProps {
  deltaHistory: number[];
  epsilon?: number;
}

export function ConvergenceChart({ deltaHistory, epsilon = 1.0 }: ConvergenceChartProps) {
  if (deltaHistory.length === 0) {
    return (
      <Card className="flex h-40 items-center justify-center">
        <p className="text-sm text-zinc-400">No turns yet — start chatting to see ΔS_t</p>
      </Card>
    );
  }

  const data = deltaHistory.map((delta, i) => ({ turn: i + 1, delta }));

  return (
    <Card>
      <p className="mb-3 text-xs font-medium uppercase tracking-wider text-zinc-400">
        Schema edit distance ΔS_t per turn
      </p>
      <ResponsiveContainer width="100%" height={140}>
        <LineChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
          <XAxis
            dataKey="turn"
            tick={{ fontSize: 11 }}
            label={{ value: "Turn", position: "insideRight", offset: -4, fontSize: 11 }}
          />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip
            formatter={(v: number) => [v.toFixed(2), "ΔS_t"]}
            labelFormatter={(l) => `Turn ${l}`}
          />
          <ReferenceLine
            y={epsilon}
            stroke="#f59e0b"
            strokeDasharray="4 2"
            label={{ value: "ε", position: "right", fontSize: 11, fill: "#f59e0b" }}
          />
          <Line
            type="monotone"
            dataKey="delta"
            stroke="#7c3aed"
            strokeWidth={2}
            dot={{ r: 3, fill: "#7c3aed" }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="mt-1 text-[10px] text-zinc-400">
        Convergence when ΔS_t &lt; ε = {epsilon} for 3 consecutive turns
      </p>
    </Card>
  );
}