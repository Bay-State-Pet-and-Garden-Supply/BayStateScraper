// Tauri IPC Types
export interface SetupStatus {
  first_run_complete: boolean;
  chromium_installed: boolean;
  has_api_key: boolean;
  api_url: string;
  runner_name: string;
}

export interface Settings {
  api_url: string;
  runner_name: string;
  headless: boolean;
  auto_update: boolean;
}

export interface RunnerStatus {
  online: boolean;
  runner_name: string;
  version: string;
  current_job: string | null;
  last_job_time: string | null;
}

export interface ScraperInfo {
  name: string;
  display_name: string;
  status: string;
  last_run: string | null;
}

export interface ChromiumProgress {
  progress: number;
  status: "starting" | "downloading" | "extracting" | "complete" | "error";
  message: string;
}
