# PaperBeacon project guidance

Always follow the recipient privacy policy in [.cursor/rules/recipient-privacy.mdc](.cursor/rules/recipient-privacy.mdc), especially when adding recipients, changing scheduled reports, committing, or publishing.

Run `python3 scripts/check_recipient_privacy.py --staged` before committing. Real email addresses belong only in ignored local environment files; public examples use reserved placeholder domains.
