use anyhow::Result as Fallible;
use itertools::Itertools;
use std::collections::{HashMap, HashSet};
use std::iter::FromIterator;

use cincinnati::plugins::internal::openshift_secondary_metadata_parser::plugin::graph_data_model::Channel;

static CHANNEL_ORDER: [&'static str; 3] = ["stable", "fast", "candidate"];

pub async fn run(channels_vec: &Vec<Channel>) -> Fallible<()> {
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
        .filter_map(|c| c.name.split("-").last())
        .unique()
        .collect();

    // Prepare a list of expected channels, ordered according to the rule
    for r in releases {
        let release_vec: Vec<String> = CHANNEL_ORDER
            .iter()
            .map(|v| format!("{}-{}", v, r))
            .collect();
        // Iterate over pairs
        for (a, b) in release_vec.iter().tuple_windows() {
            // Check that channels are present
            if channels.get(a).is_none() || channels.get(b).is_none() {
                continue;
            }
            // All releases in channel 'a' must be present in channel 'b'
            let hashset_a: HashSet<_> = HashSet::from_iter(channels[a].iter().cloned());
            let hashset_b: HashSet<_> = HashSet::from_iter(channels[b].iter().cloned());
            let diff = hashset_a.difference(&hashset_b);
            for r in diff {
                errors.push(format!("Release {} present in {}, but not in {}", r, a, b))
            }
        }
    }
    if errors.is_empty() {
        Ok(())
    } else {
        Err(anyhow::anyhow!("Error in channel ordering: {:?}", errors))
    }
}
