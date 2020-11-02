use cincinnati::plugins::internal::release_scrape_dockerv2::plugin;
use cincinnati::plugins::internal::release_scrape_dockerv2::registry;
use cincinnati::Release;

use anyhow::Context;
use anyhow::Result as Fallible;
use semver::Version;
use std::collections::HashSet;
use std::str::FromStr;

pub async fn run(found_versions: &HashSet<Version>) -> Fallible<Vec<Release>> {
    let settings = plugin::ReleaseScrapeDockerv2Settings::default();
    let cache = registry::cache::new();
    let registry = registry::Registry::try_from_str(&settings.registry)
        .context(format!("Parsing {} as Registry", &settings.registry))?;

    println!("Scraping Quay registry");
    let released_metadata: Vec<Release> = registry::fetch_releases(
        &registry,
        &settings.repository,
        settings.username.as_ref().map(String::as_ref),
        settings.password.as_ref().map(String::as_ref),
        cache,
        &settings.manifestref_key,
        settings.fetch_concurrency,
    )
    .await
    .context("failed to fetch all release metadata")?
    .into_iter()
    .map(|r| r.into())
    .collect();

    let released_versions: HashSet<Version> = released_metadata
        .clone()
        .into_iter()
        .map(|m| Version::from_str(m.version()).unwrap())
        .collect();

    println!("Verifying all releases are uploaded");
    let missing_versions: HashSet<&Version> =
        found_versions.difference(&released_versions).collect();
    if missing_versions.is_empty() {
        Ok(released_metadata.clone())
    } else {
        Err(anyhow::anyhow!(
            "Missing the following versions in scraped images: {:?}",
            missing_versions
        ))
    }
}
