use anyhow::{anyhow, bail, Context, Error, Result as Fallible};
use cincinnati::{ConcreteRelease, Release};
use lazy_static::lazy_static;
use semver::{Identifier, Version};
use std::collections::HashSet;
use std::iter::FromIterator;
use std::str::FromStr;

static METADATA_URL_KEY: &str = "url";
static ERRATA_URL_REGEX_STR: &str =
    r"https://access.redhat.com/errata/RH[BS]{1}A-[0-9]{4}:[0-9]{3}";
static SKIP_VERSIONS: &[&str] = &["4.6.5", "4.6.6", "4.7.35", "4.8.9", "4.9.2", "0.0.0"];
// TODO: Declare these in Cincinnati
static SPECIAL_PRES: &[&str] = &["amd64", "arm64", "ppc64le", "s390x"];

lazy_static! {
    static ref ERRATA_URL_REGEX_RE: regex::Regex =
        regex::Regex::new(ERRATA_URL_REGEX_STR).expect("could not create regex");
}

fn ensure_no_errors(
    v: Vec<Result<ConcreteRelease, Error>>,
    context: &str,
) -> Fallible<Vec<ConcreteRelease>> {
    Ok(v.into_iter()
        .collect::<Result<Vec<ConcreteRelease>, Error>>()
        .context(context.to_string())?)
}

pub fn run(found_versions: &[Release]) -> Fallible<Vec<Release>> {
    println!("Verifying all supported releases have errata link");

    let mut versions: Vec<Release> = found_versions.to_vec();
    // Skip fc/rc versions (any predicate except known)
    versions.retain(|r| {
        let version = Version::from_str(r.version()).unwrap();
        let pre = HashSet::from_iter(version.pre.iter().cloned());
        pre.is_empty()
            || SPECIAL_PRES
                .iter()
                .map(|p| Identifier::AlphaNumeric(p.to_string()))
                .collect::<HashSet<_>>()
                .intersection(&pre)
                .count()
                != 0
    });
    // Filter out versions in skip list (ignoring all suffixes)
    versions.retain(|r| {
        let version = Version::from_str(r.version()).unwrap();
        let version_with_no_predicate = Version::new(version.major, version.minor, version.patch);
        !SKIP_VERSIONS.contains(&version_with_no_predicate.to_string().as_str())
    });

    // Ensure these are concrete releases
    let (concrete_versions, errs): (Vec<_>, Vec<_>) = versions
        .into_iter()
        .map(|r| match r {
            Release::Concrete(v) => Ok(v),
            _ => bail!("{} is an abstract release", r.version()),
        })
        .partition(Result::is_ok);
    ensure_no_errors(errs, "Abstract releases found")?;

    // Collect releases without URL metadata
    let unpacked_versions: Vec<_> = concrete_versions
        .iter()
        .map(|r| r.as_ref().unwrap())
        .collect();
    let (errata_urls, errs): (Vec<_>, Vec<_>) = unpacked_versions
        .into_iter()
        .map(|r| {
            r.metadata
                .contains_key(METADATA_URL_KEY)
                .then(|| r.clone())
                .ok_or(anyhow!("Missing {} key in {}", METADATA_URL_KEY, r.version))
        })
        .partition(Result::is_ok);
    ensure_no_errors(errs, "Releases missing URL metadata key")?;

    // Ensure errata URLs match the format
    errata_urls
        .into_iter()
        .map(|r| r.as_ref().unwrap().clone())
        .filter(|r| !ERRATA_URL_REGEX_RE.is_match(r.metadata.get(METADATA_URL_KEY).unwrap()))
        .map(|r| {
            Err(anyhow!(
                "Invalid errata link in {}: {:#?}",
                r.version,
                r.metadata
            ))
        })
        .collect::<Result<_, _>>()
        .context("Malformed errata URL")?;
    Ok(vec![])
}

#[cfg(test)]
mod tests {
    use crate::check_errata_link::{run, METADATA_URL_KEY};
    use cincinnati::{ConcreteRelease, Release};
    pub use std::collections::HashMap as MapImpl;
    use test_case::test_case;

    fn make_release_with_metadata(version: &str, key: &str, value: &str) -> Release {
        let mut metadata = MapImpl::new();
        metadata.insert(key.to_string(), value.to_string());
        Release::Concrete(ConcreteRelease {
            version: String::from(version),
            payload: String::from("image/1.0.0"),
            metadata: metadata,
        })
    }

    #[test_case(
        "4.9.0",
        METADATA_URL_KEY,
        "https://access.redhat.com/errata/RHSA-2019:2594",
        true; "Happy path"
    )]
    #[test_case(
        "4.9.0+amd64",
        METADATA_URL_KEY,
        "https://access.redhat.com/errata/RHSA-2019:2594",
        true; "Arch suffix"
    )]
    #[test_case(
        "4.9.0-fc.0",
        "some other non-url key",
        "https://wait.thats.not.redhat.com/doh",
        true; "FC version"
    )]
    #[test_case(
        "0.0.0",
        "some other non-url key",
        "https://wait.thats.not.redhat.com/doh",
        true; "Known exception"
    )]
    #[test_case(
        "4.12.84",
        METADATA_URL_KEY,
        "https://access.redhat.com/errata/RHBA-2026:317",
        true; "three digit errata numbers"
    )]
    #[test_case(
        "4.9.0",
        "some other non-url key",
        "https://access.redhat.com/errata/RHSA-2019:2594",
        false; "No metadata.url key"
    )]
    #[test_case(
        "4.9.0+arm64",
        "some other non-url key",
        "https://access.redhat.com/errata/RHSA-2019:2594",
        false; "arch suffix, no metadata.url key"
    )]
    #[test_case(
        "4.6.35",
        METADATA_URL_KEY,
        "https://wait.thats.not.redhat.com/doh",
        false; "Mismatching errata URL"
    )]
    fn test_verify_errata_links(
        version: &str,
        metadata_key: &str,
        errata_link: &str,
        expected: bool,
    ) {
        let found_versions = vec![make_release_with_metadata(
            version,
            metadata_key,
            errata_link,
        )];
        let result = run(&found_versions);
        assert_eq!(result.is_ok(), expected, "{:#?}", result);
    }
}
