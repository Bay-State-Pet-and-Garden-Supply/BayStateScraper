import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { Loader2, Download, CheckCircle, AlertCircle, RefreshCw } from "lucide-react";
import type { ChromiumProgress } from "../types/tauri";

interface ChromiumInstallerProps {
  onComplete: () => void;
  onSkip?: () => void;
}

export default function ChromiumInstaller({ onComplete, onSkip }: ChromiumInstallerProps) {
  const [status, setStatus] = useState<"idle" | "downloading" | "complete" | "error">("idle");
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState("Ready to download Chromium browser");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Listen for progress events from Tauri
    const unlisten = listen<ChromiumProgress>("chromium-progress", (event) => {
      const { progress: p, status: s, message: m } = event.payload;
      setProgress(p);
      setMessage(m);
      
      if (s === "complete") {
        setStatus("complete");
        setTimeout(onComplete, 1500);
      } else if (s === "error") {
        setStatus("error");
        setError(m);
      } else {
        setStatus("downloading");
      }
    });

    return () => {
      unlisten.then((fn) => fn());
    };
  }, [onComplete]);

  const startInstall = async () => {
    setStatus("downloading");
    setError(null);
    setProgress(0);
    setMessage("Starting Chromium download...");

    try {
      await invoke("install_chromium");
    } catch (e) {
      setStatus("error");
      setError(String(e));
    }
  };

  const retry = () => {
    setStatus("idle");
    setError(null);
    setProgress(0);
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-[400px] p-8">
      <div className="w-full max-w-md">
        {/* Icon */}
        <div className="flex justify-center mb-6">
          {status === "idle" && (
            <div className="w-20 h-20 rounded-full bg-forest-50 flex items-center justify-center">
              <Download className="w-10 h-10 text-forest-500" />
            </div>
          )}
          {status === "downloading" && (
            <div className="w-20 h-20 rounded-full bg-blue-50 flex items-center justify-center">
              <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
            </div>
          )}
          {status === "complete" && (
            <div className="w-20 h-20 rounded-full bg-green-50 flex items-center justify-center">
              <CheckCircle className="w-10 h-10 text-green-500" />
            </div>
          )}
          {status === "error" && (
            <div className="w-20 h-20 rounded-full bg-red-50 flex items-center justify-center">
              <AlertCircle className="w-10 h-10 text-red-500" />
            </div>
          )}
        </div>

        {/* Title */}
        <h2 className="text-2xl font-bold text-center text-gray-800 mb-2">
          {status === "idle" && "Install Chromium Browser"}
          {status === "downloading" && "Downloading Chromium..."}
          {status === "complete" && "Installation Complete!"}
          {status === "error" && "Installation Failed"}
        </h2>

        {/* Description */}
        <p className="text-center text-gray-600 mb-6">
          {status === "idle" && "The scraper needs Chromium to run. This is a one-time download (~150MB)."}
          {status === "downloading" && message}
          {status === "complete" && "Chromium is ready. You can now use the scraper."}
          {status === "error" && (error || "An error occurred during installation.")}
        </p>

        {/* Progress Bar */}
        {status === "downloading" && (
          <div className="mb-6">
            <div className="flex justify-between text-sm text-gray-600 mb-1">
              <span>Downloading...</span>
              <span>{progress}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-3">
              <div
                className="bg-forest-500 h-3 rounded-full transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {/* Buttons */}
        <div className="flex flex-col gap-3">
          {status === "idle" && (
            <>
              <button
                onClick={startInstall}
                className="w-full py-3 px-6 bg-forest-500 text-white font-semibold rounded-lg hover:bg-forest-600 transition-colors flex items-center justify-center gap-2"
              >
                <Download size={20} />
                Download Chromium
              </button>
              {onSkip && (
                <button
                  onClick={onSkip}
                  className="w-full py-2 text-gray-500 hover:text-gray-700 transition-colors text-sm"
                >
                  Skip for now (scraper won't work)
                </button>
              )}
            </>
          )}

          {status === "error" && (
            <button
              onClick={retry}
              className="w-full py-3 px-6 bg-gray-100 text-gray-700 font-semibold rounded-lg hover:bg-gray-200 transition-colors flex items-center justify-center gap-2"
            >
              <RefreshCw size={20} />
              Try Again
            </button>
          )}
        </div>

        {/* Info Text */}
        {status === "idle" && (
          <p className="text-xs text-gray-400 text-center mt-4">
            This download is from the official Playwright repository and is safe.
          </p>
        )}
      </div>
    </div>
  );
}
