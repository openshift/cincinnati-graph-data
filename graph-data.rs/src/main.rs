mod check_releases;
mod verify_yaml;
use anyhow::Result as Fallible;

async fn run_all_tests() -> Fallible<()> {
    let found_versions = verify_yaml::run().await?;
    check_releases::run(&found_versions).await?;
    Ok(())
}

fn main() -> Fallible<()> {
    let mut runtime = tokio::runtime::Runtime::new()?;
    runtime.block_on(run_all_tests())
}
