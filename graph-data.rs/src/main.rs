mod check_releases;
mod check_signatures;
mod verify_yaml;

use anyhow::Result as Fallible;

use cincinnati::Release;

async fn run_all_tests() -> Fallible<()> {
    let found_versions = verify_yaml::run().await?;
    let releases: Vec<Release> = check_releases::run(&found_versions).await?;
    Ok(())
}

fn main() -> Fallible<()> {
    let mut runtime = tokio::runtime::Runtime::new()?;
    runtime.block_on(run_all_tests())
}
