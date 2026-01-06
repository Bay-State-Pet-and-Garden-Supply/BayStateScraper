import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Activity, CheckCircle, Clock, XCircle } from "lucide-react";

interface RunnerStatus {
  online: boolean;
  runner_name: string;
  version: string;
  current_job: string | null;
  last_job_time: string | null;
}

export default function Dashboard() {
  const [status, setStatus] = useState<RunnerStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchStatus();
  }, []);

  const fetchStatus = async () => {
    try {
      const result = await invoke<RunnerStatus>("get_status");
      setStatus(result);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-forest-green"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-800">Dashboard</h2>
        <button
          onClick={fetchStatus}
          className="px-4 py-2 bg-forest-green text-white rounded-lg hover:bg-dark-green transition-colors"
        >
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <StatusCard
          title="Runner Status"
          value={status?.online ? "Online" : "Offline"}
          icon={status?.online ? CheckCircle : XCircle}
          color={status?.online ? "green" : "red"}
        />
        <StatusCard
          title="Runner Name"
          value={status?.runner_name || "Unknown"}
          icon={Activity}
          color="blue"
        />
        <StatusCard
          title="Current Job"
          value={status?.current_job || "Idle"}
          icon={Clock}
          color="yellow"
        />
      </div>

      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold mb-4">Recent Activity</h3>
        <div className="text-gray-500 text-center py-8">
          No recent activity. Run a scraper to see results here.
        </div>
      </div>
    </div>
  );
}

interface StatusCardProps {
  title: string;
  value: string;
  icon: React.ElementType;
  color: "green" | "red" | "blue" | "yellow";
}

function StatusCard({ title, value, icon: Icon, color }: StatusCardProps) {
  const colorClasses = {
    green: "bg-green-50 text-green-700 border-green-200",
    red: "bg-red-50 text-red-700 border-red-200",
    blue: "bg-blue-50 text-blue-700 border-blue-200",
    yellow: "bg-yellow-50 text-yellow-700 border-yellow-200",
  };

  return (
    <div className={`rounded-lg border p-6 ${colorClasses[color]}`}>
      <div className="flex items-center gap-3 mb-2">
        <Icon size={24} />
        <span className="font-medium">{title}</span>
      </div>
      <p className="text-2xl font-bold">{value}</p>
    </div>
  );
}
