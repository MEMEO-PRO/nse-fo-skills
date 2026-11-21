# Security

- Credentials are read only from environment variables or the OS keychain (`keyring`),
  never from files in the repo, `SKILL.md` or logs. Order logs pass through a redaction filter.
- The order-send path requires a per-machine HMAC confirmation token (`~/.nsefno/.confirm_key`,
  mode 600) bound to the exact payload and valid for 60 seconds.
- Report vulnerabilities privately via GitHub Security Advisories on this repository.
