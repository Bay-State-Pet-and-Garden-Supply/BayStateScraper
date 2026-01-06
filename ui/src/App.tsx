import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import Dashboard from "./components/Dashboard";
import Scrapers from "./components/Scrapers";
import Settings from "./components/Settings";
import Sidebar from "./components/Sidebar";
import SetupWizard from "./components/SetupWizard";
import type { SetupStatus } from "./types/tauri";

type View = "dashboard" | "scrapers" | "settings";

function App() {
  const [currentView, setCurrentView] = useState<View>("dashboard");
  const [isFirstRun, setIsFirstRun] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    checkSetupStatus();
  }, []);

  const checkSetupStatus = async () => {
    try {
      const status = await invoke<SetupStatus>("get_setup_status");
      setIsFirstRun(!status.first_run_complete);
    } catch (e) {
      console.error("Failed to check setup status:", e);
      setIsFirstRun(true);
    } finally {
      setLoading(false);
    }
  };

  const handleSetupComplete = () => {
    setIsFirstRun(false);
  };

  const renderView = () => {
    switch (currentView) {
      case "dashboard":
        return <Dashboard />;
      case "scrapers":
        return <Scrapers />;
      case "settings":
        return <Settings />;
      default:
        return <Dashboard />;
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-forest-500 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading...</p>
        </div>
      </div>
    );
  }

  if (isFirstRun) {
    return <SetupWizard onComplete={handleSetupComplete} />;
  }

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar currentView={currentView} onNavigate={setCurrentView} />
      <main className="flex-1 overflow-auto p-6">{renderView()}</main>
    </div>
  );
}

export default App;
