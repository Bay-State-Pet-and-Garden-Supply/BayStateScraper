use directories::ProjectDirs;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

/// Application settings stored in the user's app data directory.
/// API keys are NOT stored here - they go in the OS keychain.
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct AppSettings {
    pub api_url: String,
    pub runner_name: String,
    pub headless: bool,
    pub auto_update: bool,
    pub first_run_complete: bool,
    pub chromium_installed: bool,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            api_url: "https://app.baystatepet.com".to_string(),
            runner_name: whoami::fallible::hostname().unwrap_or_else(|_| "Desktop Runner".to_string()),
            headless: true,
            auto_update: true,
            first_run_complete: false,
            chromium_installed: false,
        }
    }
}

/// Get the application data directory.
/// - macOS: ~/Library/Application Support/com.baystate.scraper/
/// - Windows: %APPDATA%\baystate\scraper\
/// - Linux: ~/.local/share/baystate-scraper/
pub fn get_app_data_dir() -> PathBuf {
    ProjectDirs::from("com", "baystate", "scraper")
        .map(|p| p.data_dir().to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."))
}

/// Get the path to the browsers directory for Playwright.
pub fn get_browsers_dir() -> PathBuf {
    get_app_data_dir().join("browsers")
}

/// Load settings from disk, returning defaults if file doesn't exist.
pub fn load_settings() -> AppSettings {
    let path = get_app_data_dir().join("settings.json");
    fs::read_to_string(&path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

/// Save settings to disk.
pub fn save_settings(settings: &AppSettings) -> Result<(), String> {
    let dir = get_app_data_dir();
    fs::create_dir_all(&dir).map_err(|e| format!("Failed to create app data dir: {}", e))?;
    
    let path = dir.join("settings.json");
    let json = serde_json::to_string_pretty(settings)
        .map_err(|e| format!("Failed to serialize settings: {}", e))?;
    
    fs::write(&path, json).map_err(|e| format!("Failed to write settings: {}", e))?;
    
    Ok(())
}

/// Update a single setting and persist.
pub fn update_settings<F>(updater: F) -> Result<AppSettings, String>
where
    F: FnOnce(&mut AppSettings),
{
    let mut settings = load_settings();
    updater(&mut settings);
    save_settings(&settings)?;
    Ok(settings)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_settings() {
        let settings = AppSettings::default();
        assert_eq!(settings.api_url, "https://app.baystatepet.com");
        assert!(!settings.first_run_complete);
    }
}
