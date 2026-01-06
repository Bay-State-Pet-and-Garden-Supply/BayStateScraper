import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Check, Loader2, Save, TestTube } from "lucide-react";

interface Settings {
  api_url: string;
  api_key: string;
  runner_name: string;
  headless: boolean;
  auto_update: boolean;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>({
    api_url: "",
    api_key: "",
    runner_name: "Local Runner",
    headless: true,
    auto_update: true,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<boolean | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    try {
      const result = await invoke<Settings>("get_settings");
      setSettings(result);
    } catch (e) {
      console.error("Failed to fetch settings:", e);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveSuccess(false);

    try {
      await invoke("save_settings", { settings });
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (e) {
      console.error("Failed to save settings:", e);
    } finally {
      setSaving(false);
    }
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);

    try {
      const result = await invoke<boolean>("test_connection", {
        apiUrl: settings.api_url,
        apiKey: settings.api_key,
      });
      setTestResult(result);
    } catch (e) {
      setTestResult(false);
    } finally {
      setTesting(false);
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
    <div className="space-y-6 max-w-2xl">
      <h2 className="text-2xl font-bold text-gray-800">Settings</h2>

      <div className="bg-white rounded-lg shadow p-6 space-y-6">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            API URL
          </label>
          <input
            type="text"
            value={settings.api_url}
            onChange={(e) =>
              setSettings({ ...settings, api_url: e.target.value })
            }
            placeholder="https://your-app.vercel.app"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-forest-green focus:border-transparent"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            API Key
          </label>
          <input
            type="password"
            value={settings.api_key}
            onChange={(e) =>
              setSettings({ ...settings, api_key: e.target.value })
            }
            placeholder="bsr_..."
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-forest-green focus:border-transparent"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Runner Name
          </label>
          <input
            type="text"
            value={settings.runner_name}
            onChange={(e) =>
              setSettings({ ...settings, runner_name: e.target.value })
            }
            placeholder="My Runner"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-forest-green focus:border-transparent"
          />
        </div>

        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={settings.headless}
              onChange={(e) =>
                setSettings({ ...settings, headless: e.target.checked })
              }
              className="rounded border-gray-300 text-forest-green focus:ring-forest-green"
            />
            <span className="text-sm text-gray-700">Headless Mode</span>
          </label>

          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={settings.auto_update}
              onChange={(e) =>
                setSettings({ ...settings, auto_update: e.target.checked })
              }
              className="rounded border-gray-300 text-forest-green focus:ring-forest-green"
            />
            <span className="text-sm text-gray-700">Auto Update</span>
          </label>
        </div>

        <div className="flex items-center gap-4 pt-4 border-t">
          <button
            onClick={testConnection}
            disabled={testing || !settings.api_url}
            className="flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors disabled:opacity-50"
          >
            {testing ? (
              <Loader2 className="animate-spin" size={16} />
            ) : (
              <TestTube size={16} />
            )}
            Test Connection
          </button>

          {testResult !== null && (
            <span
              className={`text-sm ${
                testResult ? "text-green-600" : "text-red-600"
              }`}
            >
              {testResult ? "Connection successful!" : "Connection failed"}
            </span>
          )}

          <div className="flex-1" />

          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-6 py-2 bg-forest-green text-white rounded-lg hover:bg-dark-green transition-colors disabled:opacity-50"
          >
            {saving ? (
              <Loader2 className="animate-spin" size={16} />
            ) : saveSuccess ? (
              <Check size={16} />
            ) : (
              <Save size={16} />
            )}
            {saveSuccess ? "Saved!" : "Save Settings"}
          </button>
        </div>
      </div>
    </div>
  );
}
