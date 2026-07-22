#!/bin/bash
# Generate the RSA keypair identity uses to sign JWTs (RS256).
# Only the public key ever leaves identity — via /.well-known/jwks.json.
set -e

KEYS_DIR="services/identity/keys"
mkdir -p "$KEYS_DIR"

if [ -f "$KEYS_DIR/private.pem" ]; then
  echo "Keys already exist at $KEYS_DIR — refusing to overwrite. Delete them first if you really want to rotate."
  exit 1
fi

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$KEYS_DIR/private.pem"
openssl rsa -pubout -in "$KEYS_DIR/private.pem" -out "$KEYS_DIR/public.pem"

chmod 600 "$KEYS_DIR/private.pem"
echo "Keypair written to $KEYS_DIR/{private,public}.pem"
