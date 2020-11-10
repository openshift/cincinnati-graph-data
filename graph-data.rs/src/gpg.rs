/// Tiny crate to verify message signature and format
use anyhow::Result as Fallible;
use anyhow::{format_err, Context};
use bytes::buf::BufExt;
use bytes::Bytes;
use serde::Deserialize;
use serde_json;
use std::fs::{read_dir, File};

use pgp::composed::message::Message;
use pgp::composed::signed_key::SignedPublicKey;
use pgp::Deserializable;

// Location of public keys
static PUBKEYS_DIR: &str = "/usr/local/share/public-keys/";

// Signature format
#[derive(Deserialize)]
struct SignatureImage {
  #[serde(rename = "docker-manifest-digest")]
  digest: String,
}

#[derive(Deserialize)]
struct SignatureCritical {
  image: SignatureImage,
}

#[derive(Deserialize)]
struct Signature {
  critical: SignatureCritical,
}

/// Keyring is a collection of public keys
pub type Keyring = Vec<SignedPublicKey>;

/// Create a Keyring from a dir of public keys
pub fn load_public_keys() -> Fallible<Keyring> {
  let mut result: Keyring = vec![];
  for entry in read_dir(PUBKEYS_DIR).context("Reading public keys dir")? {
    let path = &entry?.path();
    let path_str = match path.to_str() {
      None => continue,
      Some(p) => p,
    };
    let file = File::open(path).context(format!("Reading {}", path_str))?;
    let (pubkey, _) =
      SignedPublicKey::from_armor_single(file).context(format!("Parsing {}", path_str))?;
    match pubkey.verify() {
      Err(err) => return Err(format_err!("{:?}", err)),
      Ok(_) => result.push(pubkey),
    };
  }
  Ok(result)
}

/// Verify that signature is valid and contains expected digest
pub async fn verify_signature(
  public_keys: &Keyring,
  body: Bytes,
  expected_digest: &str,
) -> Fallible<()> {
  let msg = Message::from_bytes(body.reader()).context("Parsing message")?;

  // Verify signature using provided public keys
  if !public_keys.iter().any(|ref k| msg.verify(k).is_ok()) {
    return Err(format_err!("No matching key found to decrypt {:#?}", msg));
  }

  // Deserialize the message
  let contents = match msg.get_content().context("Reading contents")? {
    None => return Err(format_err!("Empty message received")),
    Some(m) => m,
  };
  let signature: Signature = serde_json::from_slice(&contents).context("Deserializing message")?;
  let message_digest = signature.critical.image.digest;
  if message_digest == expected_digest {
    Ok(())
  } else {
    Err(format_err!(
      "Valid signature, but digest mismatches: {}",
      message_digest
    ))
  }
}
