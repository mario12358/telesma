---
tag: kubernetes
keywords: kubernetes, k8s, kubectl, manifest, deployment, pod, ingress, helm, kustomize, namespace, configmap, probe, networkpolicy, cluster
---

# Guidelines: Kubernetes

## Style

- YAML with 2 spaces, one resource per file named `<kind>-<name>.yaml` (`deployment-api.yaml`, `service-api.yaml`); `---`-joined multi-document files only as generated output
- Every resource sets `metadata.namespace` explicitly — never rely on the kubeconfig's current context
- Standard labels on every resource: `app.kubernetes.io/name`, `app.kubernetes.io/component`, `app.kubernetes.io/part-of`, `app.kubernetes.io/version`; selectors use `name` + `component` only (selectors are immutable — never put a version in them)
- Resource names are lowercase kebab-case and stable, without environment or version suffixes (the namespace/overlay carries those)
- Image references are immutable: `registry/repo:<git-sha or version>@sha256:…`; a mutable tag never appears in a manifest
- Field order: `apiVersion`, `kind`, `metadata`, `spec`; inside a container: `name`, `image`, `args`, `env`, `ports`, `resources`, probes, `securityContext`
- Ports are named (`name: http`) and probes/Services reference the name, not the number
- Format with `yamlfmt` (or `prettier --parser yaml`) and lint with `kube-linter`; run them, do not argue with them

## Project structure

- Kustomize is the default (plain YAML, patches, no templating); Helm only to consume third-party charts, never to template your own application
- `deploy/base/` — one file per resource + `kustomization.yaml` listing them; `deploy/overlays/<env>/` — one overlay per environment with patches for replicas, resources, hostnames and image tags
- Overlays patch with strategic-merge or JSON6902 patches; they never copy a whole resource from base
- Image tags are set in the overlay through `images:` → `newTag:`/`digest:` in `kustomization.yaml`, bumped by CI — never edited by hand in the Deployment
- ConfigMaps and Secrets come from `configMapGenerator` / `secretGenerator` with hash suffixes so a config change rolls the pods
- Third-party charts pinned to an exact chart version under `deploy/charts/<name>/` with a committed `values-<env>.yaml` per environment
- The base is deployable on its own to a dev namespace; environment differences live only in overlays

## Tests

- Every PR renders every overlay: `kustomize build deploy/overlays/<env>` (or `helm template`) must succeed with zero warnings
- Schema validation of the rendered output with `kubeconform -strict -summary -ignore-missing-schemas` (CRD schemas via `-schema-location`) — a required CI job
- Policy tests on the rendered output with `kube-linter lint` (or `conftest` with your own Rego): no mutable tags, requests/limits present, three probes present, non-root, no privileged — a violation fails the build
- `kubectl apply --dry-run=server -f -` against a `kind` cluster in CI for admission checks that a schema cannot express
- Smoke test after every deploy: `kubectl rollout status deployment/<name> -n <ns> --timeout=120s`, then one request to the readiness path; a failed rollout triggers `kubectl rollout undo`
- Test failure modes on purpose in `kind`: delete a pod and the Service still answers; a missing ConfigMap key fails readiness instead of crash-looping; `kubectl drain` a node and the PDB holds
- The only path to a shared cluster is CI applying rendered manifests; nothing is tested by `kubectl apply` from a laptop

## Workloads and resources

- `Deployment` for stateless services, `StatefulSet` only for ordered identity or persistent storage, `Job`/`CronJob` for finite work; never a bare `Pod`
- Every container sets `resources.requests` and `resources.limits.memory` with request = limit for memory; set `requests.cpu`, leave `limits.cpu` off unless a quota policy requires it (CPU limits throttle and look like slow code)
- Three probes with distinct jobs: `startupProbe` (slow boots; `failureThreshold × periodSeconds` ≥ worst-case start), `readinessProbe` (dependencies reachable → receive traffic), `livenessProbe` (process stuck → restart). Liveness never checks dependencies — a down database would restart every pod
- Probes hit cheap unauthenticated endpoints (`/healthz` live, `/readyz` ready) on the named port
- Rolling updates: `maxUnavailable: 0`, `maxSurge: 1` (or `25%`) for user-facing services; `minReadySeconds: 5`; `terminationGracePeriodSeconds` ≥ longest request + a `preStop` sleep of a few seconds so endpoints drop the pod before SIGTERM; the process handles SIGTERM by draining and exiting
- Production overlays run `replicas ≥ 2` with `topologySpreadConstraints` across nodes/zones and a `PodDisruptionBudget` (`maxUnavailable: 1`); use a `HorizontalPodAutoscaler` where load varies, and then do not also set a hard `replicas:` in that overlay
- One process per container; sidecars only for a real cross-cutting concern (proxy, log shipper)

## Configuration and secrets

- Non-secret config in a `ConfigMap`, consumed via `envFrom.configMapRef` or mounted files; one ConfigMap per component, not one per key
- Secrets never in git — neither plain nor base64. Use an external manager through External Secrets Operator (`ExternalSecret` → generated `Secret`) or Sealed Secrets (encrypted blobs committed, private key only in the cluster); the manifest tree holds references, not values
- Secrets are consumed as mounted files or `env.valueFrom.secretKeyRef`; never interpolated into `args:` (visible in `kubectl describe`)
- A changed Secret or ConfigMap rolls the pods (generator hash suffix or a reloader annotation); the application reads them at start, not per request

## Security

- `securityContext` on every container: `runAsNonRoot: true`, `runAsUser` ≥ 1000, `readOnlyRootFilesystem: true` (plus an `emptyDir` for `/tmp`), `allowPrivilegeEscalation: false`, `capabilities.drop: ["ALL"]`, `seccompProfile.type: RuntimeDefault`
- Namespaces labelled `pod-security.kubernetes.io/enforce: restricted`; a manifest that fails `restricted` is fixed, not exempted
- A dedicated `ServiceAccount` per workload with `automountServiceAccountToken: false` unless the pod calls the API; RBAC `Role`s scoped to the namespace with named resources — never `cluster-admin`, never `verbs: ["*"]`
- Default-deny `NetworkPolicy` (ingress and egress) per namespace, then explicit allows: ingress controller → app, app → database, app → DNS (`kube-system`, port 53 UDP/TCP); a new dependency is a new rule, never a wider one
- Ingress with a `tls:` block only (cert-manager annotations); no `hostNetwork`, `hostPID`, `hostPath`, `hostPort`
- Private registry pulls via `imagePullSecrets` on the ServiceAccount; `imagePullPolicy: IfNotPresent` with digests

## What to avoid

- `image: app:latest` or an untagged image; `imagePullPolicy: Always` as a substitute for immutable tags
- Secrets committed in any encoding — base64 is not encryption
- `kubectl apply` / `kubectl edit` by hand against production; the cluster drifts and the next CI run silently reverts the fix
- A liveness probe that checks the database (cascading restarts); a slow service without `startupProbe` (restart loop); liveness and readiness pointing at the same endpoint
- Missing `resources` (BestEffort pods are evicted first) or CPU limits set from a guess
- `privileged: true`, `runAsUser: 0`, a mounted container-runtime socket
- `namespace: default`, a missing namespace, hostnames or replica counts hardcoded in base instead of an overlay
- Templating your own YAML with Helm `{{ }}` where a Kustomize patch does the job; copying whole resources into overlays
- One replica, no PDB and `maxUnavailable: 1` in production — every rollout is an outage
- `type: NodePort` or one `type: LoadBalancer` per service exposed to the internet instead of a single Ingress
