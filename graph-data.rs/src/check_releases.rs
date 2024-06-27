use cincinnati::plugins::internal::release_scrape_dockerv2::plugin;
use cincinnati::plugins::internal::release_scrape_dockerv2::registry;
use cincinnati::Release;

use anyhow::Context;
use anyhow::Result as Fallible;
use semver::Version;
use std::collections::HashSet;
use std::str::FromStr;

fn compare_metadata(
    released_metadata: Vec<Release>,
    found_versions: &HashSet<Version>,
) -> Fallible<Vec<Release>> {
    let released_versions: HashSet<Version> = released_metadata
        .clone()
        .into_iter()
        .map(|m| Version::from_str(m.version()).unwrap())
        .collect();

    println!("Verifying all releases are uploaded");
    let missing_versions: HashSet<&Version> =
        found_versions.difference(&released_versions).collect();
    if missing_versions.is_empty() {
        Ok(released_metadata)
    } else {
        Err(anyhow::anyhow!(
            "Missing the following versions in scraped images: {:?}",
            missing_versions
        ))
    }
}

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
        Some(Vec::new()),
    )
    .await
    .context("failed to fetch all release metadata")?
    .into_iter()
    .map(|r| r.into())
    .collect();
    compare_metadata(released_metadata, found_versions)
}

#[cfg(test)]
mod tests {
    use super::*;
    use cincinnati::ConcreteRelease;
    pub use std::collections::HashMap as MapImpl;
    use std::iter::FromIterator;
    use test_case::test_case;

    fn prepare_metadata() -> Vec<Release> {
        let r1 = Release::Concrete(ConcreteRelease {
            version: String::from("1.0.0"),
            payload: String::from("image/1.0.0"),
            metadata: MapImpl::new(),
        });
        let r2 = Release::Concrete(ConcreteRelease {
            version: String::from("2.0.0"),
            payload: String::from("image/2.0.0"),
            metadata: MapImpl::new(),
        });
        return vec![r1, r2];
    }

    #[test_case(vec![], true)]
    #[test_case(vec!["1.0.0"], true)]
    #[test_case(vec!["1.0.0", "2.0.0"], true)]
    #[test_case(vec!["1.0.0", "3.0.0"], false)]
    #[test_case(vec!["1.0.0", "2.0.0", "3.0.0"], false)]
    fn test_compare_metadata(versions: Vec<&str>, expected: bool) {
        let test_metadata = prepare_metadata();
        let found_versions =
            HashSet::<_, _>::from_iter(versions.into_iter().map(|m| Version::from_str(m).unwrap()));
        assert_eq!(
            compare_metadata(test_metadata, &found_versions,).is_ok(),
            expected
        );
    }
}
