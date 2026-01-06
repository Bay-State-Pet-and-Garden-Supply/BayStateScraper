#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

mod commands;
mod keychain;
mod storage;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![
            // Setup & Configuration
            commands::get_setup_status,
            commands::save_api_key,
            commands::get_api_key,
            commands::save_settings,
            commands::get_settings,
            commands::complete_setup,
            commands::test_connection,
            // Chromium Installation
            commands::install_chromium,
            commands::check_chromium_installed,
            // Scraper Execution
            commands::get_status,
            commands::get_scrapers,
            commands::run_scraper,
            // Utilities
            commands::get_app_data_dir,
            commands::reset_app,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
