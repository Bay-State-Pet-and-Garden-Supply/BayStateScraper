import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  ChevronRight,
  ChevronLeft,
  Loader2,
  CheckCircle,
  AlertCircle,
  ExternalLink,
  Wifi,
  Key,
  User,
} from "lucide-react";
import type { SetupStatus, Settings } from "../types/tauri";
import ChromiumInstaller from "./ChromiumInstaller";

interface SetupWizardProps {
  onComplete: () => void;
}

type Step = "welcome" | "runner" | "apiKey" | "chromium" | "complete";

export default function SetupWizard({ onComplete }: SetupWizardProps) {
  const [currentStep, setCurrentStep] = useState<Step>("welcome");
  const [settings, setSettings] = useState<Settings>({
    api_url: "https://app.baystatepet.com",
    runner_name: "",
    headless: true,
    auto_update: true,
  });
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [testResult, setTestResult] = useState<"success" | "error" | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [chromiumInstalled, setChromiumInstalled] = useState(false);

  useEffect(() => {
    // Load existing status if any
    loadSetupStatus();
  }, []);

  const loadSetupStatus = async () => {
    try {
      const status = await invoke<SetupStatus>("get_setup_status");
      if (status.runner_name) {
        setSettings((s) => ({ ...s, runner_name: status.runner_name }));
      }
      if (status.api_url) {
        setSettings((s) => ({ ...s, api_url: status.api_url }));
      }
      setChromiumInstalled(status.chromium_installed);
    } catch (e) {
      console.error("Failed to load setup status:", e);
    }
  };

  const steps: Step[] = ["welcome", "runner", "apiKey", "chromium", "complete"];
  const stepIndex = steps.indexOf(currentStep);

  const canProceed = () => {
    switch (currentStep) {
      case "welcome":
        return true;
      case "runner":
        return settings.runner_name.trim().length > 0;
      case "apiKey":
        return apiKey.startsWith("bsr_") && testResult === "success";
      case "chromium":
        return chromiumInstalled;
      case "complete":
        return true;
      default:
        return false;
    }
  };

  const goNext = async () => {
    if (currentStep === "runner") {
      // Save settings before proceeding
      try {
        await invoke("save_settings", { settings });
      } catch (e) {
        console.error("Failed to save settings:", e);
      }
    } else if (currentStep === "apiKey") {
      // Save API key
      try {
        await invoke("save_api_key", { key: apiKey });
      } catch (e) {
        console.error("Failed to save API key:", e);
      }
    } else if (currentStep === "chromium" && chromiumInstalled) {
      setCurrentStep("complete");
      return;
    } else if (currentStep === "complete") {
      // Complete setup
      try {
        await invoke("complete_setup");
        onComplete();
      } catch (e) {
        console.error("Failed to complete setup:", e);
        onComplete(); // Proceed anyway
      }
      return;
    }

    const nextIndex = stepIndex + 1;
    if (nextIndex < steps.length) {
      setCurrentStep(steps[nextIndex]);
      setTestResult(null);
      setTestError(null);
    }
  };

  const goBack = () => {
    const prevIndex = stepIndex - 1;
    if (prevIndex >= 0) {
      setCurrentStep(steps[prevIndex]);
      setTestResult(null);
      setTestError(null);
    }
  };

  const testConnection = async () => {
    if (!apiKey.startsWith("bsr_")) {
      setTestResult("error");
      setTestError("API key must start with 'bsr_'");
      return;
    }

    setLoading(true);
    setTestResult(null);
    setTestError(null);

    try {
      const result = await invoke<boolean>("test_connection", {
        apiUrl: settings.api_url,
        apiKey: apiKey,
      });
      setTestResult(result ? "success" : "error");
      if (!result) {
        setTestError("Connection failed. Please check your API key.");
      }
    } catch (e) {
      setTestResult("error");
      setTestError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const renderStepIndicator = () => (
    <div className="flex items-center justify-center mb-8">
      {steps.slice(0, -1).map((step, i) => (
        <div key={step} className="flex items-center">
          <div
            className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-colors ${
              i < stepIndex
                ? "bg-forest-500 text-white"
                : i === stepIndex
                ? "bg-forest-500 text-white ring-4 ring-forest-100"
                : "bg-gray-200 text-gray-500"
            }`}
          >
            {i < stepIndex ? <CheckCircle size={16} /> : i + 1}
          </div>
          {i < steps.length - 2 && (
            <div
              className={`w-16 h-1 mx-1 transition-colors ${
                i < stepIndex ? "bg-forest-500" : "bg-gray-200"
              }`}
            />
          )}
        </div>
      ))}
    </div>
  );

  const renderWelcome = () => (
    <div className="text-center">
      <div className="w-24 h-24 mx-auto mb-6 rounded-full bg-forest-100 flex items-center justify-center p-4">
        <img
          src="/logo.png"
          alt="Bay State"
          className="w-full h-full object-contain"
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = "none";
          }}
        />
      </div>
      <h1 className="text-3xl font-bold text-gray-800 mb-4">
        Welcome to Bay State Scraper
      </h1>
      <p className="text-gray-600 max-w-md mx-auto mb-8">
        Let's set up your scraper runner. This will only take a minute. You'll need:
      </p>
      <div className="flex flex-col gap-3 max-w-sm mx-auto text-left mb-8">
        <div className="flex items-center gap-3 text-gray-700">
          <User className="text-forest-500" size={20} />
          <span>A name for this runner</span>
        </div>
        <div className="flex items-center gap-3 text-gray-700">
          <Key className="text-forest-500" size={20} />
          <span>Your API key from the Admin Panel</span>
        </div>
        <div className="flex items-center gap-3 text-gray-700">
          <Wifi className="text-forest-500" size={20} />
          <span>An internet connection</span>
        </div>
      </div>
      
      <button
        onClick={goNext}
        className="w-full max-w-sm mx-auto flex items-center justify-center gap-2 px-8 py-3 bg-forest-500 text-white font-semibold rounded-lg hover:bg-forest-600 transition-colors shadow-lg hover:shadow-xl transform hover:-translate-y-0.5 transition-all"
      >
        Get Started
        <ChevronRight size={20} />
      </button>
    </div>
  );

  const renderRunnerStep = () => (
    <div className="max-w-md mx-auto">
      <h2 className="text-2xl font-bold text-gray-800 mb-2 text-center">
        Runner Configuration
      </h2>
      <p className="text-gray-600 text-center mb-8">
        Give this runner a name so you can identify it in the admin panel.
      </p>

      <div className="space-y-6">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Runner Name
          </label>
          <input
            type="text"
            value={settings.runner_name}
            onChange={(e) =>
              setSettings({ ...settings, runner_name: e.target.value })
            }
            placeholder="e.g., Office Computer, John's Laptop"
            className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-forest-500 focus:border-transparent text-lg"
            autoFocus
          />
          <p className="mt-2 text-sm text-gray-500">
            This helps you identify which computer is running scrapes.
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            API URL
          </label>
          <input
            type="text"
            value={settings.api_url}
            onChange={(e) =>
              setSettings({ ...settings, api_url: e.target.value })
            }
            placeholder="https://app.baystatepet.com"
            className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-forest-500 focus:border-transparent"
          />
          <p className="mt-2 text-sm text-gray-500">
            Leave as default unless you have a custom deployment.
          </p>
        </div>
      </div>
    </div>
  );

  const renderApiKeyStep = () => (
    <div className="max-w-md mx-auto">
      <h2 className="text-2xl font-bold text-gray-800 mb-2 text-center">
        API Key
      </h2>
      <p className="text-gray-600 text-center mb-8">
        Enter your API key to connect this runner to Bay State.
      </p>

      <div className="space-y-6">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            API Key
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value);
              setTestResult(null);
              setTestError(null);
            }}
            placeholder="bsr_..."
            className={`w-full px-4 py-3 border rounded-lg focus:ring-2 focus:ring-forest-500 focus:border-transparent font-mono ${
              testResult === "error"
                ? "border-red-300 bg-red-50"
                : testResult === "success"
                ? "border-green-300 bg-green-50"
                : "border-gray-300"
            }`}
            autoFocus
          />
        </div>

        <a
          href={`${settings.api_url}/admin/scraper-network`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center gap-2 text-forest-600 hover:text-forest-700 text-sm"
        >
          <ExternalLink size={16} />
          Get your API key from the Admin Panel
        </a>

        <button
          onClick={testConnection}
          disabled={loading || !apiKey}
          className="w-full py-3 px-6 bg-gray-100 text-gray-700 font-semibold rounded-lg hover:bg-gray-200 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {loading ? (
            <Loader2 className="animate-spin" size={20} />
          ) : testResult === "success" ? (
            <CheckCircle className="text-green-500" size={20} />
          ) : testResult === "error" ? (
            <AlertCircle className="text-red-500" size={20} />
          ) : (
            <Wifi size={20} />
          )}
          {loading
            ? "Testing..."
            : testResult === "success"
            ? "Connection Verified!"
            : testResult === "error"
            ? "Test Failed - Try Again"
            : "Test Connection"}
        </button>

        {testError && (
          <p className="text-red-600 text-sm text-center">{testError}</p>
        )}
      </div>
    </div>
  );

  const renderChromiumStep = () => (
    <ChromiumInstaller
      onComplete={() => {
        setChromiumInstalled(true);
        setCurrentStep("complete");
      }}
      onSkip={() => setCurrentStep("complete")}
    />
  );

  const renderComplete = () => (
    <div className="text-center">
      <div className="w-24 h-24 mx-auto mb-6 rounded-full bg-green-100 flex items-center justify-center">
        <CheckCircle className="w-12 h-12 text-green-500" />
      </div>
      <h1 className="text-3xl font-bold text-gray-800 mb-4">Setup Complete!</h1>
      <p className="text-gray-600 max-w-md mx-auto mb-8">
        Your runner "{settings.runner_name}" is ready to use. You can now start
        running scrapes from the dashboard.
      </p>
      <div className="bg-gray-50 rounded-lg p-4 max-w-sm mx-auto text-left">
        <h3 className="font-semibold text-gray-700 mb-2">Configuration Summary:</h3>
        <div className="space-y-1 text-sm text-gray-600">
          <p>
            <span className="font-medium">Runner:</span> {settings.runner_name}
          </p>
          <p>
            <span className="font-medium">API URL:</span> {settings.api_url}
          </p>
          <p>
            <span className="font-medium">Chromium:</span>{" "}
            {chromiumInstalled ? "Installed" : "Not installed"}
          </p>
        </div>
      </div>
    </div>
  );

  return (
    <div className="h-screen bg-gradient-to-b from-forest-50 to-white flex flex-col overflow-hidden">
      {/* Header */}
      <div className="p-4 flex items-center justify-center flex-shrink-0">
        <h1 className="text-xl font-bold text-forest-700">Bay State Scraper</h1>
      </div>

      {/* Step Indicator */}
      <div className="flex-shrink-0">
        {currentStep !== "complete" && renderStepIndicator()}
      </div>

      {/* Content */}
      <div className="flex-1 flex items-start justify-center p-4 overflow-y-auto">
        <div className="w-full max-w-2xl py-4">
          {currentStep === "welcome" && renderWelcome()}
          {currentStep === "runner" && renderRunnerStep()}
          {currentStep === "apiKey" && renderApiKeyStep()}
          {currentStep === "chromium" && renderChromiumStep()}
          {currentStep === "complete" && renderComplete()}
        </div>
      </div>

      {/* Navigation */}
      <div className="p-6 border-t bg-white flex-shrink-0 shadow-lg z-10">
        <div className="max-w-2xl mx-auto flex justify-between">
          <button
            onClick={goBack}
            disabled={stepIndex === 0}
            className="flex items-center gap-2 px-6 py-3 text-gray-600 hover:text-gray-800 transition-colors disabled:opacity-0"
          >
            <ChevronLeft size={20} />
            Back
          </button>

          <button
            onClick={goNext}
            disabled={!canProceed() || (currentStep === "chromium" && !chromiumInstalled)}
            className="flex items-center gap-2 px-8 py-3 bg-forest-500 text-white font-semibold rounded-lg hover:bg-forest-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {currentStep === "complete" ? "Get Started" : "Continue"}
            {currentStep !== "complete" && <ChevronRight size={20} />}
          </button>
        </div>
      </div>
    </div>
  );
}
