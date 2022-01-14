use anyhow::Result as Fallible;
use itertools::Itertools;
use std::collections::{HashMap, HashSet};
use std::iter::FromIterator;

use cincinnati::plugins::internal::openshift_secondary_metadata_parser::plugin::graph_data_model::Channel;

static CHANNEL_ORDER: [&str; 3] = ["stable", "fast", "candidate"];

fn validate_two_channels(
    channels: &HashMap<String, Vec<semver::Version>>,
    a: &str,
    b: &str,
) -> Option<String> {
    // Skip test if channel 'a' doesn't exist
    channels.get(a)?;
    // Channel 'b' must be present
    if channels.get(b).is_none() {
        return Some(format!("Channel {} exists, but not {}", a, b));
    }
    // All releases in channel 'a' must be present in channel 'b'
    let hashset_a: HashSet<_> = HashSet::from_iter(channels[a].iter().cloned());
    let hashset_b: HashSet<_> = HashSet::from_iter(channels[b].iter().cloned());
    let diff = hashset_a.difference(&hashset_b);
    let error_message = diff
        .map(|r| format!("Release {} present in {}, but not in {}", r, a, b))
        .join("\n");
    if error_message.is_empty() {
        None
    } else {
        Some(error_message)
    }
}

pub async fn run(channels_vec: &[Channel]) -> Fallible<()> {
    let mut errors: Vec<String> = vec![];

    println!("Verifying all releases are following channel order");
    // Make a hashmap of channels so that we could fetch a list of releases by name
    let channels: HashMap<String, Vec<semver::Version>> = channels_vec
        .iter()
        .map(|c| (c.name.clone(), c.versions.clone()))
        .collect();

    // Collect a list of releases (4.6, 4.5 etc.)
    let releases: Vec<&str> = channels_vec
        .iter()
        .filter_map(|c| c.name.split('-').last())
        .unique()
        .collect();

    // Prepare a list of expected channels, ordered according to the rule
    for r in releases {
        if r == "4.1" {
            continue;
        }
        let release_vec: Vec<String> = CHANNEL_ORDER
            .iter()
            .map(|v| format!("{}-{}", v, r))
            .collect();
        // Iterate over pairs of channels, returing optional errors and pushing errors to the list
        for e in release_vec
            .iter()
            .tuple_windows()
            .map(|(a, b)| validate_two_channels(&channels, a, b))
            .filter(|e| e.is_some())
            .collect::<Vec<_>>()
        {
            errors.push(e.unwrap())
        }
    }
    if errors.is_empty() {
        Ok(())
    } else {
        Err(anyhow::anyhow!("Error in channel ordering: {:?}", errors))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use test_case::test_case;

    static CHANNEL_A: &str = "a";
    static CHANNEL_B: &str = "b";
    static CHANNEL_EMPTY: &str = "empty";
    static NO_SUCH_CHANNEL: &str = "foobar";

    fn get_test_channels() -> HashMap<String, Vec<semver::Version>> {
        let channel_a = (
            CHANNEL_A.to_string(),
            vec![semver::Version::parse("1.0.0").unwrap()],
        );
        let channel_b = (
            CHANNEL_B.to_string(),
            vec![
                semver::Version::parse("1.0.0").unwrap(),
                semver::Version::parse("2.0.0").unwrap(),
            ],
        );
        let channel_empty = (CHANNEL_EMPTY.to_string(), Vec::<semver::Version>::new());
        HashMap::<_, _>::from_iter(vec![channel_a, channel_b, channel_empty].into_iter())
    }

    // Releases from empty channel would always be valid
    #[test_case(CHANNEL_EMPTY, CHANNEL_A, None)]
    // Channel is always valid when compared to itself
    #[test_case(CHANNEL_A, CHANNEL_A, None)]
    // All channels from a are in b
    #[test_case(CHANNEL_A, CHANNEL_B, None)]
    // No such channel
    #[test_case(NO_SUCH_CHANNEL, CHANNEL_B, None)]
    // Some channels in a are not b
    #[test_case(CHANNEL_B, CHANNEL_A, Some("Release 2.0.0 present in b, but not in a".to_string()))]
    // Can't compare to inexisting channel
    #[test_case(CHANNEL_A, NO_SUCH_CHANNEL, Some("Channel a exists, but not foobar".to_string()))]
    fn test_validate_two_channels(
        first_channel: &str,
        second_channel: &str,
        expected: Option<String>,
    ) {
        let channels = get_test_channels();
        assert_eq!(
            validate_two_channels(
                &channels,
                &first_channel.to_string(),
                &second_channel.to_string(),
            ),
            expected
        );
    }
}
