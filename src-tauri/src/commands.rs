use serde::{Deserialize, Serialize};
use std::process::Command;
use tauri::command;

#[derive(Serialize, Deserialize)]
pub struct RunnerStatus {
    pub online: bool,
    pub runner_name: String,
    pub version: String,
    pub current_job: Option<String>,
    pub last_job_time: Option<String>,
}

#[derive(Serialize, Deserialize)]
pub struct ScraperInfo {
    pub name: String,
    pub display_name: String,
    pub status: String,
    pub last_run: Option<String>,
}

#[derive(Serialize, Deserialize)]
pub struct Settings {
    pub api_url: String,
    pub api_key: String,
    pub runner_name: String,
    pub headless: bool,
    pub auto_update: bool,
}

#[derive(Serialize, Deserialize)]
pub struct ScrapeResult {
    pub success: bool,
    pub products_found: i32,
    pub errors: Vec<String>,
    pub logs: Vec<String>,
}

#[command]
pub async fn get_status() -> Result<RunnerStatus, String> {
    Ok(RunnerStatus {
        online: true,
        runner_name: std::env::var("RUNNER_NAME").unwrap_or_else(|_| "Local Runner".to_string()),
        version: env!("CARGO_PKG_VERSION").to_string(),
        current_job: None,
        last_job_time: None,
    })
}

#[command]
pub async fn run_scraper(scraper_name: String, skus: Vec<String>) -> Result<ScrapeResult, String> {
    let output = Command::new("python")
        .args([
            "-c",
            &format!(
                "import json; from scrapers.main import run_scraping; \
                 result = run_scraping('{}', {}); \
                 print(json.dumps({{'success': True, 'products_found': len(result.get('products', []))}}))",
                scraper_name,
                serde_json::to_string(&skus).unwrap_or_else(|_| "[]".to_string())
            ),
        ])
        .output()
        .map_err(|e| format!("Failed to execute scraper: {}", e))?;

    if output.status.success() {
        let stdout = String::from_utf8_lossy(&output.stdout);
        serde_json::from_str(&stdout).map_err(|e| format!("Failed to parse result: {}", e))
    } else {
        let stderr = String::from_utf8_lossy(&output.stderr);
        Err(format!("Scraper failed: {}", stderr))
    }
}

#[command]
pub async fn get_scrapers() -> Result<Vec<ScraperInfo>, String> {
    Ok(vec![
        ScraperInfo {
            name: "amazon".to_string(),
            display_name: "Amazon".to_string(),
            status: "active".to_string(),
            last_run: None,
        },
    ])
}

#[command]
pub async fn get_settings() -> Result<Settings, String> {
    Ok(Settings {
        api_url: std::env::var("SCRAPER_API_URL").unwrap_or_default(),
        api_key: std::env::var("SCRAPER_API_KEY").unwrap_or_default(),
        runner_name: std::env::var("RUNNER_NAME").unwrap_or_else(|_| "Local Runner".to_string()),
        headless: true,
        auto_update: true,
    })
}

#[command]
pub async fn save_settings(settings: Settings) -> Result<(), String> {
    std::env::set_var("SCRAPER_API_URL", &settings.api_url);
    std::env::set_var("SCRAPER_API_KEY", &settings.api_key);
    std::env::set_var("RUNNER_NAME", &settings.runner_name);
    Ok(())
}

#[command]
pub async fn test_connection(api_url: String, api_key: String) -> Result<bool, String> {
    let client = reqwest::blocking::Client::new();
    let response = client
        .get(format!("{}/api/health", api_url))
        .header("X-API-Key", api_key)
        .send()
        .map_err(|e| format!("Connection failed: {}", e))?;

    Ok(response.status().is_success())
}
