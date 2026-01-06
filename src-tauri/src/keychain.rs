use keyring::Entry;
use thiserror::Error;

const SERVICE_NAME: &str = "com.baystate.scraper";
const API_KEY_ACCOUNT: &str = "api_key";

#[derive(Error, Debug)]
pub enum KeychainError {
    #[error("Keychain access error: {0}")]
    Access(String),
    #[error("Key not found")]
    NotFound,
    #[error("Failed to store key: {0}")]
    Store(String),
}

impl From<KeychainError> for String {
    fn from(e: KeychainError) -> Self {
        e.to_string()
    }
}

/// Store the API key in the OS keychain.
/// - macOS: Stores in Keychain Access
/// - Windows: Stores in Windows Credential Manager
/// - Linux: Stores in Secret Service (GNOME Keyring/KWallet)
pub fn store_api_key(key: &str) -> Result<(), KeychainError> {
    let entry = Entry::new(SERVICE_NAME, API_KEY_ACCOUNT)
        .map_err(|e| KeychainError::Access(e.to_string()))?;
    
    entry
        .set_password(key)
        .map_err(|e| KeychainError::Store(e.to_string()))
}

/// Retrieve the API key from the OS keychain.
pub fn get_api_key() -> Result<String, KeychainError> {
    let entry = Entry::new(SERVICE_NAME, API_KEY_ACCOUNT)
        .map_err(|e| KeychainError::Access(e.to_string()))?;
    
    entry
        .get_password()
        .map_err(|e| {
            if e.to_string().contains("No matching entry") 
                || e.to_string().contains("not found")
                || e.to_string().contains("NoEntry") 
            {
                KeychainError::NotFound
            } else {
                KeychainError::Access(e.to_string())
            }
        })
}

/// Delete the API key from the OS keychain.
pub fn delete_api_key() -> Result<(), KeychainError> {
    let entry = Entry::new(SERVICE_NAME, API_KEY_ACCOUNT)
        .map_err(|e| KeychainError::Access(e.to_string()))?;
    
    entry
        .delete_credential()
        .map_err(|e| KeychainError::Store(e.to_string()))
}

/// Check if an API key exists without retrieving it.
pub fn has_api_key() -> bool {
    get_api_key().is_ok()
}

#[cfg(test)]
mod tests {
    // Note: These tests require keychain access and may prompt for permissions
    // Run with: cargo test -- --ignored
    
    #[test]
    #[ignore]
    fn test_store_and_retrieve() {
        use super::*;
        
        let test_key = "bsr_test_key_12345";
        store_api_key(test_key).unwrap();
        let retrieved = get_api_key().unwrap();
        assert_eq!(retrieved, test_key);
        delete_api_key().unwrap();
    }
}
