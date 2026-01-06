import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Play, RefreshCw } from "lucide-react";

interface ScraperInfo {
  name: string;
  display_name: string;
  status: string;
  last_run: string | null;
}

interface ScrapeResult {
  success: boolean;
  products_found: number;
  errors: string[];
  logs: string[];
}

export default function Scrapers() {
  const [scrapers, setScrapers] = useState<ScraperInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState<string | null>(null);
  const [testSkus, setTestSkus] = useState("");
  const [result, setResult] = useState<ScrapeResult | null>(null);

  useEffect(() => {
    fetchScrapers();
  }, []);

  const fetchScrapers = async () => {
    try {
      const result = await invoke<ScraperInfo[]>("get_scrapers");
      setScrapers(result);
    } catch (e) {
      console.error("Failed to fetch scrapers:", e);
    } finally {
      setLoading(false);
    }
  };

  const runScraper = async (scraperName: string) => {
    if (!testSkus.trim()) {
      alert("Please enter SKUs to test");
      return;
    }

    setRunning(scraperName);
    setResult(null);

    try {
      const skus = testSkus.split(",").map((s) => s.trim()).filter(Boolean);
      const result = await invoke<ScrapeResult>("run_scraper", {
        scraperName,
        skus,
      });
      setResult(result);
    } catch (e) {
      setResult({
        success: false,
        products_found: 0,
        errors: [String(e)],
        logs: [],
      });
    } finally {
      setRunning(null);
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
        <h2 className="text-2xl font-bold text-gray-800">Scrapers</h2>
        <button
          onClick={fetchScrapers}
          className="flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
        >
          <RefreshCw size={16} />
          Refresh
        </button>
      </div>

      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold mb-4">Test Scraper</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              SKUs (comma-separated)
            </label>
            <input
              type="text"
              value={testSkus}
              onChange={(e) => setTestSkus(e.target.value)}
              placeholder="035585499741, 123456789012"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-forest-green focus:border-transparent"
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {scrapers.map((scraper) => (
          <div
            key={scraper.name}
            className="bg-white rounded-lg shadow p-4 border border-gray-200"
          >
            <div className="flex items-center justify-between mb-3">
              <h4 className="font-semibold text-gray-800">
                {scraper.display_name}
              </h4>
              <span
                className={`px-2 py-1 text-xs rounded-full ${
                  scraper.status === "active"
                    ? "bg-green-100 text-green-700"
                    : "bg-gray-100 text-gray-600"
                }`}
              >
                {scraper.status}
              </span>
            </div>
            <p className="text-sm text-gray-500 mb-4">
              {scraper.last_run
                ? `Last run: ${scraper.last_run}`
                : "Never run"}
            </p>
            <button
              onClick={() => runScraper(scraper.name)}
              disabled={running !== null}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-forest-green text-white rounded-lg hover:bg-dark-green transition-colors disabled:opacity-50"
            >
              {running === scraper.name ? (
                <>
                  <RefreshCw className="animate-spin" size={16} />
                  Running...
                </>
              ) : (
                <>
                  <Play size={16} />
                  Test Scraper
                </>
              )}
            </button>
          </div>
        ))}
      </div>

      {result && (
        <div
          className={`rounded-lg p-6 ${
            result.success
              ? "bg-green-50 border border-green-200"
              : "bg-red-50 border border-red-200"
          }`}
        >
          <h3
            className={`text-lg font-semibold mb-2 ${
              result.success ? "text-green-800" : "text-red-800"
            }`}
          >
            {result.success ? "Scrape Successful" : "Scrape Failed"}
          </h3>
          <p className="text-sm">
            Products found: <strong>{result.products_found}</strong>
          </p>
          {result.errors.length > 0 && (
            <div className="mt-4">
              <p className="font-medium text-red-700">Errors:</p>
              <ul className="list-disc list-inside text-sm text-red-600">
                {result.errors.map((error, i) => (
                  <li key={i}>{error}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
