mod check_channels;
mod check_errata_link;
mod check_releases;
mod check_signatures;
mod verify_yaml;

use anyhow::Result as Fallible;

use cincinnati::Release;

async fn run_all_tests() -> Fallible<()> {
    let (found_versions, channels) = verify_yaml::run().await?;
    check_channels::run(&channels).await?;
    let releases: Vec<Release> = check_releases::run(&found_versions).await?;
    check_signatures::run(&releases, &found_versions).await?;
    check_errata_link::run(&releases)?;
    Ok(())
}

fn main() -> Fallible<()> {
    let runtime = tokio::runtime::Runtime::new()?;
    runtime.block_on(run_all_tests())
}
