# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's **Report a vulnerability** feature when
it is available. Do not publish API keys, credentials, personal data, or exploit details in a public
issue.

Include the affected file or feature, reproduction steps, likely impact, and any suggested
mitigation. The maintainer can then coordinate disclosure and a fix.

## Credential handling

Companies House credentials belong in a local `.env` file or Streamlit secrets. Both locations are
ignored by Git. If a credential is committed or exposed, revoke it immediately and replace it; merely
removing it from the latest commit does not remove it from Git history.
