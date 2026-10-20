use base::config::keys;
use hbb_common::config;

#[cfg(all(feature = "joey-support", feature = "joey-admin"))]
compile_error!("Build joey-support and joey-admin separately");

const SERVER: &str = "support.joeymeijer.nl";
const PUBLIC_KEY: &str = "rWJkRGVzwEgI011JqfPCLU2r38PlOIga8kam8LB4hlU=";

pub(crate) fn init() {
    let mut settings = config::OVERWRITE_SETTINGS.write().unwrap();
    settings.insert(keys::OPTION_CUSTOM_RENDEZVOUS_SERVER.into(), SERVER.into());
    settings.insert(keys::OPTION_KEY.into(), PUBLIC_KEY.into());
    settings.insert(keys::OPTION_RELAY_SERVER.into(), format!("{SERVER}:21117"));
    settings.insert(keys::OPTION_ALLOW_AUTO_UPDATE.into(), "N".into());
    drop(settings);

    config::OVERWRITE_LOCAL_SETTINGS
        .write()
        .unwrap()
        .insert(keys::OPTION_ENABLE_CHECK_UPDATE.into(), "N".into());

    // Keep APP_NAME as RustDesk: it also selects the service, IPC and config paths.
    let mut hard = config::HARD_SETTINGS.write().unwrap();
    hard.insert("disable-account".into(), "Y".into());
    hard.insert("disable-ab".into(), "Y".into());
    hard.insert(
        "conn-type".into(),
        if cfg!(feature = "joey-support") {
            "incoming"
        } else {
            "both"
        }
        .into(),
    );
    drop(hard);

    config::BUILTIN_SETTINGS.write().unwrap().insert(
        "joey-display-name".into(),
        if cfg!(feature = "joey-support") {
            "Joey Meijer Support"
        } else {
            "Joey Meijer Support - Beheer"
        }
        .into(),
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn configured_client_keeps_rustdesk_identity_and_applies_variant() {
        init();
        assert_eq!(config::APP_NAME.read().unwrap().as_str(), "RustDesk");
        assert_eq!(
            config::Config::get_option(keys::OPTION_CUSTOM_RENDEZVOUS_SERVER),
            "support.joeymeijer.nl"
        );
        assert_eq!(config::Config::get_option(keys::OPTION_KEY), PUBLIC_KEY);
        assert_eq!(
            config::Config::get_option(keys::OPTION_RELAY_SERVER),
            "support.joeymeijer.nl:21117"
        );
        assert_eq!(config::is_incoming_only(), cfg!(feature = "joey-support"));
        assert!(!config::is_outgoing_only());
        assert_eq!(
            config::LocalConfig::get_option(keys::OPTION_ENABLE_CHECK_UPDATE),
            "N"
        );
        assert_eq!(
            config::Config::get_option(keys::OPTION_ALLOW_AUTO_UPDATE),
            "N"
        );
    }
}
