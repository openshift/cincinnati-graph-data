use cincinnati::plugins::internal::dkrv2_openshift_secondary_metadata_scraper::gpg;
use cincinnati::plugins::internal::dkrv2_openshift_secondary_metadata_scraper::plugin::{
    DEFAULT_SIGNATURE_BASEURL, DEFAULT_SIGNATURE_FETCH_TIMEOUT_SECS,
};

use anyhow::Result as Fallible;
use anyhow::{format_err, Context};

use futures::stream::StreamExt;
use lazy_static::lazy_static;
use reqwest::{Client, ClientBuilder};
use semver::Version;
use std::collections::HashSet;
use std::path::PathBuf;
use std::str::FromStr;
use std::time::Duration;
use url::Url;

use cincinnati::Release;

lazy_static! {
  // Location of public keys
  static ref PUBKEYS_DIR: PathBuf = PathBuf::from("/usr/local/share/public-keys/");
  // base url for signature storage - see https://github.com/openshift/cluster-update-keys/blob/master/stores/store-openshift-official-release-mirror

  static ref BASE_URL: Url = Url::parse(DEFAULT_SIGNATURE_BASEURL).unwrap();
}

// Skip some versions from 4.0 / 4.1 / 4.2 times
// https://issues.redhat.com/browse/ART-2397
static SKIP_VERSIONS: &[&str] = &[
    "4.1.0-rc.3+amd64",
    "4.1.0-rc.5+amd64",
    "4.1.0-rc.4+amd64",
    "4.1.0-rc.0+amd64",
    "4.1.0-rc.8+amd64",
    "4.1.37+amd64",
    "4.2.11+amd64",
    "4.3.0-rc.0+amd64",
    "4.6.0-fc.3+s390x",
    // 4.1.0+amd64 is signed with CI key
    "4.1.0+amd64",
    // new 4.4.0+s390x version resulted from error
    "4.4.0+s390x",
];

/// Extract payload value from Release if it is a Concrete release
fn payload_from_release(release: &Release) -> Fallible<String> {
    match release {
        Release::Concrete(c) => Ok(c.payload.clone()),
        _ => Err(format_err!("not a concrete release")),
    }
}

/// Generate URLs for signature store and attempt to find a valid signature
#[allow(clippy::ptr_arg)]
async fn find_signatures_for_version(
    client: &Client,
    public_keys: &gpg::Keyring,
    release: &Release,
) -> Fallible<()> {
    let payload = payload_from_release(release)?;
    let digest = payload
        .split('@')
        .last()
        .ok_or_else(|| format_err!("could not parse payload '{:?}'", payload))?;

    gpg::verify_signatures_for_digest(client, &BASE_URL, public_keys, digest).await
}

/// Iterate versions and return true if Release is included
fn is_release_in_versions(versions: &HashSet<Version>, release: &Release) -> bool {
    // Check that release version is not in skip list
    if SKIP_VERSIONS.contains(&release.version()) {
        return false;
    }
    // Strip arch identifier
    let stripped_version = release
        .version()
        .split('+')
        .next()
        .ok_or_else(|| release.version())
        .unwrap();
    let version = Version::from_str(stripped_version).unwrap();
    versions.contains(&version)
}

pub async fn run(releases: &[Release], found_versions: &HashSet<semver::Version>) -> Fallible<()> {
    println!("Checking release signatures");

    // Initialize keyring
    let public_keys = gpg::load_public_keys(&PUBKEYS_DIR)?;

    // Prepare http client
    let client: Client = ClientBuilder::new()
        .gzip(true)
        .timeout(Duration::from_secs(DEFAULT_SIGNATURE_FETCH_TIMEOUT_SECS))
        .build()
        .context("Building reqwest client")?;

    // Limit the concurrency; otherwise, we can make more requests than the system can handle
    const SIGNATURE_CHECK_CONCURRENCY: usize = usize::MAX;

    // Filter scraped images - skip CI images
    let results: Vec<Fallible<()>> = futures::stream::iter(
        releases
            .iter()
            .filter(|r| is_release_in_versions(found_versions, r)),
    )
    // Attempt to find signatures for filtered releases
    .map(|r| find_signatures_for_version(&client, &public_keys, r))
    .buffered(SIGNATURE_CHECK_CONCURRENCY)
    .collect::<Vec<Fallible<()>>>()
    .await
    // Filter to keep errors only
    .into_iter()
    .filter(|e| e.is_err())
    .collect();
    if results.is_empty() {
        Ok(())
    } else {
        Err(format_err!("Signature check errors: {:#?}", results))
    }
}
