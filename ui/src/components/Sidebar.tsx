import { Home, Settings, Bug } from "lucide-react";

type View = "dashboard" | "scrapers" | "settings";

interface SidebarProps {
  currentView: View;
  onNavigate: (view: View) => void;
}

export default function Sidebar({ currentView, onNavigate }: SidebarProps) {
  const navItems = [
    { id: "dashboard" as View, label: "Dashboard", icon: Home },
    { id: "scrapers" as View, label: "Scrapers", icon: Bug },
    { id: "settings" as View, label: "Settings", icon: Settings },
  ];

  return (
    <aside className="w-64 bg-forest-green text-white flex flex-col">
      <div className="p-4 border-b border-dark-green">
        <h1 className="text-xl font-bold">Bay State Scraper</h1>
        <p className="text-sm text-green-200">Runner Application</p>
      </div>

      <nav className="flex-1 p-2">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = currentView === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg mb-1 transition-colors ${
                isActive
                  ? "bg-dark-green text-white"
                  : "text-green-100 hover:bg-dark-green/50"
              }`}
            >
              <Icon size={20} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="p-4 border-t border-dark-green text-sm text-green-200">
        <p>Version 1.0.0</p>
      </div>
    </aside>
  );
}
