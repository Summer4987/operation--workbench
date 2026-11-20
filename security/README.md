# Production security hardening

Run `scripts/deploy_security_hardening.zsh` only from a clean, pulled GitHub `main` on the Mac mini. The cloud verifies/imports an incremental Git bundle of that exact GitHub-main commit into `/opt/xiong-security-source`; it never deploys developer working-tree files. This avoids slow cloud-to-GitHub transfers and a race with concurrent main updates.

The reviewed deployment moves existing Nginx business routes to the existing verified IP certificate, redirects browser/API HTTP requests to HTTPS, preserves the configured signed/encrypted `/agent-wecom/callback` and ACME challenge, and retains the phone `/avatar/` gateway. Session-signing secrets are rotated locally and personal sessions revoked: all users must log in again. Passwords, accounts, orders and catalogs are retained. HTTPS smoke tests exercise owner compatibility, one-store data/export, denied full-data routes and Beijing scope using temporary records that are cleaned up.

The old dashboard binds only to loopback. A dedicated persistent firewall chain blocks public 8088, 6080 and 631 while preserving loopback, SSH and HTTPS. Beijing catalog, order history and submission require store or dashboard identity and exact authorized store scope; dashboard view permission does not grant edit. An absent/unavailable authorization service fails closed.

Backups, local secrets and migration reports stay on production hosts, never GitHub. The deployment refuses an unexpected order-code baseline and restores the prior business routes/code if validation fails. Independent legacy-port containment stays enabled even if the HTTPS portion rolls back. Apply is intentionally one-shot: inspect `/var/lib/xiong-security/applied.json` and backups before a later release.

The certificate gateway repository also preserves the optional HTTPS business-route include during regeneration (`scripts/deploy-tls-compat-macmini.zsh` in `zhiqiweixing-deepseek`). Existing certificate renewal continues on the Mac mini.

Regression: 64 security/client tests pass plus five subtests; gateway repository has six passing tests. One pre-existing inventory test asserts the removed `LDXXX00014` SKU and is excluded from the security run. The broader ordering suite also has a notification test that fails identically on the pre-fix GitHub baseline; security changes do not modify that notification path.
