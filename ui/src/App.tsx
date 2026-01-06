import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import Dashboard from "./components/Dashboard";
import Scrapers from "./components/Scrapers";
import Settings from "./components/Settings";
import Sidebar from "./components/Sidebar";

type View = "dashboard" | "scrapers" | "settings";

function App() {
  const [currentView, setCurrentView] = useState<View>("dashboard");

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

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar currentView={currentView} onNavigate={setCurrentView} />
      <main className="flex-1 overflow-auto p-6">{renderView()}</main>
    </div>
  );
}

export default App;
