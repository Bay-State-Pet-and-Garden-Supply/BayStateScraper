use serde::{Deserialize, Serialize};
use tauri::{command, AppHandle, Emitter};
use std::process::Stdio;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;

use crate::keychain;
use crate::storage;

// ============================================================================
// Data Types
// ============================================================================

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct SetupStatus {
    pub first_run_complete: bool,
    pub chromium_installed: bool,
    pub has_api_key: bool,
    pub api_url: String,
    pub runner_name: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct RunnerStatus {
    pub online: bool,
    pub runner_name: String,
    pub version: String,
    pub current_job: Option<String>,
    pub last_job_time: Option<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct ScraperInfo {
    pub name: String,
    pub display_name: String,
    pub status: String,
    pub last_run: Option<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Settings {
    pub api_url: String,
    pub runner_name: String,
    pub headless: bool,
    pub auto_update: bool,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct ScrapeResult {
    pub success: bool,
    pub products_found: i32,
    pub errors: Vec<String>,
    pub logs: Vec<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct ChromiumProgress {
    pub progress: u8,
    pub status: String,
    pub message: String,
}

// ============================================================================
// Setup & Configuration Commands
// ============================================================================

/// Check the current setup status (used by frontend to decide wizard vs dashboard)
#[command]
pub async fn get_setup_status() -> Result<SetupStatus, String> {
    let settings = storage::load_settings();
    let has_api_key = keychain::has_api_key();
    
    Ok(SetupStatus {
        first_run_complete: settings.first_run_complete,
        chromium_installed: settings.chromium_installed,
        has_api_key,
        api_url: settings.api_url,
        runner_name: settings.runner_name,
    })
}

/// Save the API key to the OS keychain
#[command]
pub async fn save_api_key(key: String) -> Result<(), String> {
    if !key.starts_with("bsr_") {
        return Err("API key must start with 'bsr_'".to_string());
    }
    keychain::store_api_key(&key).map_err(|e| e.to_string())
}

/// Get the API key from the OS keychain
#[command]
pub async fn get_api_key() -> Result<String, String> {
    keychain::get_api_key().map_err(|e| e.to_string())
}

/// Save general settings (not API key)
#[command]
pub async fn save_settings(settings: Settings) -> Result<(), String> {
    storage::update_settings(|s| {
        s.api_url = settings.api_url;
        s.runner_name = settings.runner_name;
        s.headless = settings.headless;
        s.auto_update = settings.auto_update;
    })?;
    Ok(())
}

/// Get current settings
#[command]
pub async fn get_settings() -> Result<Settings, String> {
    let s = storage::load_settings();
    Ok(Settings {
        api_url: s.api_url,
        runner_name: s.runner_name,
        headless: s.headless,
        auto_update: s.auto_update,
    })
}

/// Mark setup as complete
#[command]
pub async fn complete_setup() -> Result<(), String> {
    storage::update_settings(|s| {
        s.first_run_complete = true;
    })?;
    Ok(())
}

/// Test connection to the API
#[command]
pub async fn test_connection(api_url: String, api_key: String) -> Result<bool, String> {
    let client = reqwest::Client::new();
    let url = format!("{}/api/admin/scraper-network/health", api_url.trim_end_matches('/'));
    
    let response = client
        .get(&url)
        .header("X-API-Key", &api_key)
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {}", e))?;
    
    Ok(response.status().is_success())
}

// ============================================================================
// Chromium Installation Commands
// ============================================================================

/// Install Chromium browser for Playwright
/// Emits "chromium-progress" events to the window
#[command]
pub async fn install_chromium(app: AppHandle) -> Result<(), String> {
    let browsers_dir = storage::get_browsers_dir();
    
    // Create browsers directory
    std::fs::create_dir_all(&browsers_dir)
        .map_err(|e| format!("Failed to create browsers directory: {}", e))?;
    
    // Emit starting event
    let _ = app.emit("chromium-progress", ChromiumProgress {
        progress: 0,
        status: "starting".to_string(),
        message: "Starting Chromium download...".to_string(),
    });
    
    // Run playwright install chromium
    let mut cmd = Command::new("python3")
        .args(["-m", "playwright", "install", "chromium"])
        .env("PLAYWRIGHT_BROWSERS_PATH", &browsers_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to start playwright install: {}", e))?;
    
    // Stream output and emit progress
    if let Some(stderr) = cmd.stderr.take() {
        let reader = BufReader::new(stderr);
        let mut lines = reader.lines();
        let mut progress: u8 = 0;
        
        while let Ok(Some(line)) = lines.next_line().await {
            // Parse playwright output for progress
            if line.contains("Downloading") {
                progress = 10;
            } else if line.contains("%") {
                // Try to extract percentage
                if let Some(pct) = extract_percentage(&line) {
                    progress = (10 + (pct as f32 * 0.8) as u8).min(90);
                }
            } else if line.contains("Extracting") || line.contains("Installing") {
                progress = 95;
            }
            
            let _ = app.emit("chromium-progress", ChromiumProgress {
                progress,
                status: "downloading".to_string(),
                message: line,
            });
        }
    }
    
    let status = cmd.wait().await
        .map_err(|e| format!("Failed to wait for playwright install: {}", e))?;
    
    if status.success() {
        // Mark chromium as installed
        storage::update_settings(|s| {
            s.chromium_installed = true;
        })?;
        
        let _ = app.emit("chromium-progress", ChromiumProgress {
            progress: 100,
            status: "complete".to_string(),
            message: "Chromium installed successfully!".to_string(),
        });
        
        Ok(())
    } else {
        let _ = app.emit("chromium-progress", ChromiumProgress {
            progress: 0,
            status: "error".to_string(),
            message: "Chromium installation failed".to_string(),
        });
        Err("Chromium installation failed".to_string())
    }
}

fn extract_percentage(line: &str) -> Option<u8> {
    // Look for patterns like "50%" or "50.5%"
    for word in line.split_whitespace() {
        if word.ends_with('%') {
            let num_str = word.trim_end_matches('%');
            if let Ok(num) = num_str.parse::<f32>() {
                return Some(num as u8);
            }
        }
    }
    None
}

/// Check if Chromium is installed
#[command]
pub async fn check_chromium_installed() -> Result<bool, String> {
    let settings = storage::load_settings();
    if !settings.chromium_installed {
        return Ok(false);
    }
    
    // Also verify the browsers directory exists and has content
    let browsers_dir = storage::get_browsers_dir();
    let exists = browsers_dir.exists() && browsers_dir.read_dir()
        .map(|mut d| d.next().is_some())
        .unwrap_or(false);
    
    Ok(exists)
}

// ============================================================================
// Scraper Execution Commands
// ============================================================================

/// Get runner status
#[command]
pub async fn get_status() -> Result<RunnerStatus, String> {
    let settings = storage::load_settings();
    
    Ok(RunnerStatus {
        online: true,
        runner_name: settings.runner_name,
        version: env!("CARGO_PKG_VERSION").to_string(),
        current_job: None,
        last_job_time: None,
    })
}

/// Get list of available scrapers
#[command]
pub async fn get_scrapers() -> Result<Vec<ScraperInfo>, String> {
    // TODO: Call sidecar to get actual scraper list from YAML configs
    Ok(vec![
        ScraperInfo {
            name: "petfoodex".to_string(),
            display_name: "Pet Food Experts".to_string(),
            status: "active".to_string(),
            last_run: None,
        },
        ScraperInfo {
            name: "phillips".to_string(),
            display_name: "Phillips Pet".to_string(),
            status: "active".to_string(),
            last_run: None,
        },
    ])
}

/// Run a scraper with given SKUs
#[command]
pub async fn run_scraper(
    _app: AppHandle,
    scraper_name: String,
    skus: Vec<String>,
) -> Result<ScrapeResult, String> {
    let settings = storage::load_settings();
    let api_key = keychain::get_api_key().unwrap_or_default();
    let _browsers_dir = storage::get_browsers_dir();
    
    // Build config JSON to pass to sidecar
    let _config = serde_json::json!({
        "api_url": settings.api_url,
        "api_key": api_key,
        "runner_name": settings.runner_name,
        "headless": settings.headless,
    });
    
    let _args = serde_json::json!({
        "scraper_name": scraper_name,
        "skus": skus,
    });
    
    // TODO: Call sidecar binary with proper arguments
    // For now, return mock result
    Ok(ScrapeResult {
        success: true,
        products_found: skus.len() as i32,
        errors: vec![],
        logs: vec!["Scraper started".to_string()],
    })
}

// ============================================================================
// Utility Commands
// ============================================================================

/// Get the app data directory path (for debugging)
#[command]
pub async fn get_app_data_dir() -> Result<String, String> {
    Ok(storage::get_app_data_dir().to_string_lossy().to_string())
}

/// Reset app to first-run state (for testing)
#[command]
pub async fn reset_app() -> Result<(), String> {
    let _ = keychain::delete_api_key();
    storage::update_settings(|s| {
        *s = storage::AppSettings::default();
    })?;
    Ok(())
}
