---
name: java-connectivity
description: Compare remote JVM truststores and diagnose bidirectional HTTP or HTTPS failures, separating DNS, network, and Java certificate trust.
---

# Java connectivity diagnostics

Use the RemoteOpsAI MCP tools instead of writing ad hoc SSH or Python scripts.
Never put credentials, host-specific passwords, or truststore passwords in this skill.

## Workflow

1. Use `list_remote_hosts` to identify the two profiles. Each needs a cached SSH
   password from `connect_remote_host`; ask the user to reconnect a profile if needed.
   The tools below take profile names and do not switch the active host.
2. Call `inspect_java_tls_configuration(profile_name)` on each profile. Identify
   the application JVM and its PID, Java executable, truststore path, and bind
   address. If there are multiple JVMs, do not assume the first is the application.
   Supply `pid` to inspect just one process. Passwords are never returned.
3. Call `compare_java_truststores(first_profile, first_pid, second_profile,
   second_pid)`. Report both exact-file equality and certificate-fingerprint
   equality. Different file hashes can still contain the same certificates.
   Check `integrity_verified` and warnings for each store.
4. Determine the intended application URLs and ports from the user or existing
   configuration/listening-port tools. Do not assume ports 80 or 443, or scan ports.
5. Call `probe_java_http_connection(profile_name, pid, url)` from each source host
   to the other host's application. Use an HTTP URL to test plain HTTP and an HTTPS
   URL to test Java trust and hostname validation. No redirects are followed.
6. If DNS fails or resolves to an unexpected address, verify the destination's
   actual listening address. Repeat the same hostname URL with
   `address_override="<verified destination IP>"`. This overrides resolution only
   inside the temporary JVM. It preserves HTTPS hostname verification and SNI;
   never disable certificate checks or edit system DNS/hosts files.
7. Report normal hostname results separately from override results in each direction.
   Successful override probes do not mean normal hostname-based requests work.

## Interpretation

- `identical_files=true`: both truststores have the same SHA256 file hash.
- `same_certificate_fingerprints=true`: certificate fingerprints, including their
  multiplicities, match. This alone does not establish identical store metadata.
- `result.status=ok`: an HTTP response was received. Inspect `http_status`;
  redirects and 4xx/5xx responses establish reachability, not application health.
- `UnknownHostException`: DNS failure.
- `NoRouteToHostException`, `ConnectException`, or a timeout: network/connectivity
  failure; do not conclude that a firewall is responsible without evidence.
- `SSLHandshakeException` / PKIX errors: TLS or certificate trust failure.
  Certificate hostname mismatches are distinct from missing issuer trust.
- Plain HTTP does not use a truststore.
- An OS `curl` trust failure does not prove a Java truststore failure.

## Requirements and limits

- Linux SSH hosts, readable process command lines/truststores, and cached credentials.
- Truststore comparison requires the selected JDK's `keytool`. It uses a JVM
  command-line truststore password when present, without returning or persisting it.
  Missing passwords mean store integrity is not verified; some stores hide entries.
- Probes require JDK 17+ with source-file launching; DNS overrides require JDK 18+.
  Temporary source/hosts files are removed even if a probe fails. No credentials
  are written to those files or passed as process arguments.
- Probes issue one direct GET, bypass proxies, follow no redirects, read no response
  body, and supply no client certificate or application credentials.
- Discovery uses JVM command-line properties and default truststore paths.
  Probes run a fresh JVM, not code inside the application. Runtime property changes,
  application-specific SSL contexts, security/provider overrides, mutual TLS,
  and application proxy settings require separate investigation.
- HTTP success does not prove every application route or authentication flow works.
- Never modify truststores, firewall rules, DNS, or application configuration unless
  the user separately requests and authorizes that change.
