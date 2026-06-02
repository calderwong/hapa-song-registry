# Security and secret handling

<!-- HAPA_GITHUB_SECRET_SAFETY -->

This repository should be pushed to GitHub only after local secret checks pass. Do not commit real `.env` files, private keys, access tokens, API keys, local runtime tokens, database sidecars, or credential JSON.

Allowed examples: `.env.example`, `.env.sample`, `.env.template`, and documentation containing placeholder values only. Store live values in local untracked files or GitHub Actions secrets.

Before publishing, run:

```bash
git status --short
git ls-files | grep -Ei '(^|/)(\.env($|\.)|\.node_token$|.*\.pem$|.*\.key$|id_rsa|id_ed25519|.*credentials\.(json|yaml|yml|toml|ini)|.*secrets\.(json|yaml|yml|toml|ini))'
```

If a real credential was ever committed, rotate the credential and rewrite history before making the repository public.
