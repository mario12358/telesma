<!-- TELESMA_SPEC_TEMPLATE: delete this line once you start filling in the template -->

# Project technical guidelines

> ## How to use it
>
> **Fill in ONLY the fields where you depart from the defaults in `telesma/guidelines/`.**
> Empty field = use the default. Do not write "React" just because you use it anyway —
> the defaults from the guidelines take care of it. Write something only when: the client imposes it,
> the infrastructure requires it, regulations force it, the team only knows X.
>
> **Business and functional requirements** (use cases, domain model, acceptance criteria,
> mockups, diagrams) go as separate files in `telesma/spec/` — in any format.
> Claude reads every file in the directory.
>
> **Undecided**: leave it empty or write `?`. Claude will generate questions in `telesma/state/QUESTIONS.md`.
>
> Once filled in, delete the `TELESMA_SPEC_TEMPLATE` marker from the first line of the file.

---

## Stack — departures from the defaults

<!-- Fill in when imposed from outside. Otherwise leave empty. -->

- **Language / runtime**: <!-- e.g. "Java 17 — the client has a Java team" -->
- **Backend framework**: <!-- e.g. "Spring Boot — the company starter template" -->
- **Frontend framework**: <!-- e.g. "Angular 17 — existing application" -->
- **Database**: <!-- e.g. "Oracle 19c — exists, we do not change it" -->
- **ORM / DB access**: <!-- e.g. "no ORM — raw SQL" / "MyBatis" -->
- **Test runner**: <!-- e.g. "Jest — the rest of the company uses it" -->
- **Other imposed libraries**: <!-- e.g. "company auth-lib v3" -->

## Hosting and infrastructure

- **Target environment**: <!-- e.g. "on-prem RHEL 8 without Docker" / "AWS Lambda" / "Vercel" / "Kubernetes (GKE)" -->
- **Containers**: <!-- e.g. "no Docker" / "Docker + docker-compose" / "k8s manifests" -->
- **CI/CD**: <!-- e.g. "GitLab CI (company runner)" / "GitHub Actions" / "none — manual deploy" -->
- **Secrets / config**: <!-- e.g. "Vault" / "AWS Secrets Manager" / "env vars" -->
- **Monitoring / logs**: <!-- e.g. "Datadog" / "ELK" / "Grafana + Loki" -->

## External integrations

<!-- Every external system we have to talk to. Skip the section if there are none. -->

### System: [name]

- **Protocol**: <!-- REST / SOAP / GraphQL / Kafka / RabbitMQ / SFTP -->
- **Auth**: <!-- API key / OAuth2 / mTLS / Basic / none -->
- **Endpoints / docs**: <!-- link to Swagger / list of operations -->
- **SLA / limits**: <!-- rate limit, availability hours -->
- **Environments**: <!-- prod / staging / sandbox URLs + test data -->

## Non-functional requirements (when they differ from the defaults)

<!-- Write ONLY when the business spec or a regulator imposes a specific value. -->

- **Performance**: <!-- e.g. "p95 < 200 ms for GET /search" / "import of 1M rows < 5 min" -->
- **Scalability**: <!-- e.g. "100k active users, 10 GB of data per day" -->
- **Availability (SLA)**: <!-- e.g. "99.9% between 6:00–22:00" -->
- **Compliance**: <!-- e.g. "GDPR — PII pseudonymization, 5-year retention" / "PCI-DSS" / "HIPAA" -->
- **Security (overriding defaults)**: <!-- e.g. "MFA required for admins" / "TLS 1.3 only" -->
- **Localization / i18n**: <!-- e.g. "EN + DE, time zone Europe/Berlin, date format dd.MM.yyyy" -->
- **Accessibility (a11y)**: <!-- e.g. "WCAG 2.1 AA — a legal requirement" -->
- **Browser support**: <!-- e.g. "mobile Safari 14+" / "Chrome last 2 versions" -->
- **Offline**: <!-- e.g. "PWA with a service worker, sync when online" -->

## Other constraints

<!-- Anything relevant that does not fit above. Skip the section if there is nothing. -->

- 

---

## Business and functional requirements

**Do not write them here** — add separate files to `telesma/spec/` describing:

- the goal and context of the project
- use cases / user stories
- the domain model
- business rules
- acceptance criteria
- mockups / diagrams (as image files or in `telesma/spec/diagrams/`)
- a glossary of terms

Any format (.md, .txt, .pdf, .docx — binary files are auto-converted when `pandoc` is installed). In the clarification phase Claude reads every file in `telesma/spec/`.
