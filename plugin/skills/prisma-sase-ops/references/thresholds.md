# Interpretation thresholds

How to turn raw numbers into a judgement. The server already attaches a `rating`
to ADEM scores using these bands; apply the same language everywhere for
consistency.

## ADEM experience score bands

| Score | Rating | Meaning / action |
|---|---|---|
| 90–100 | excellent | Nominal. No action. |
| 80–89 | good | Healthy. |
| 70–79 | fair | Watch. Note the weakest component. |
| 50–69 | poor | **Degraded** — below the 70 action line. Investigate the weakest component. |
| 0–49 | critical | User experience is broken. Escalate. |

**The 70 line** is the documented "degraded" threshold (design doc sec.2). Any
overall score under 70 must be called out explicitly, with the weakest of the
`components` (LAN / WiFi / DNS / app) named as the likely culprit:

- **LAN low** → local wired segment / NIC / local switch.
- **WiFi low** → endpoint wireless (signal, channel congestion).
- **DNS low** → resolver latency/failures — often the quiet cause of "feels slow".
- **app low** → the SaaS/app path or the app itself, not the access network.

## Alert severity ↔ P-level

| Insights severity | Common ops label |
|---|---|
| critical | P1 |
| high | P2 |
| medium | P3 |
| low / informational | P4 / info |

When a user says "P1", filter `severity="critical"`; "P2" → `"high"`.

## Tunnel status semantics

- `up` — tunnel established and passing traffic.
- `down` — no tunnel. For a **Service Connection (SC)** this can affect HQ/data-
  centre-bound traffic; for a **Remote Network (RN)** it affects that branch.
  Always name the down tunnels and their type.
- A single SC/RN down with everything else healthy is a targeted issue; multiple
  down across regions suggests something broader — widen to `get_sase_status`
  and check alerts for a correlated cause.

## Throughput units & semantics (tunnels)

| Field | Unit | Meaning |
|---|---|---|
| `avg_throughput_kbps` | **Kbps** | average over each time bucket |
| `peak_throughput_kbps` | **Kbps** | **highest per-minute polling sample within the bucket** — not an absolute instantaneous max |
| `p95_throughput_kbps` | **Kbps** | 95th percentile — better than peak for capacity sizing |

- Convert for humans: **Mbps = Kbps ÷ 1000** (e.g. `8042.58` → ~**8.0 Mbps**).
  Misreading Kbps as Mbps is an 8000× error: 8042.58 "Mbps" would be 8 Gbps,
  which cannot fit a 1 Gbps uplink — physically impossible readings mean a
  unit misread, not a network anomaly.
- Bucket granularity grows with the query window: ≤1 h ≈ 1–3 min buckets;
  24 h = 5 min; 7–30 d rolls up to 30 min–3 h (peaks smooth out as the window
  widens — compare like windows only).
- `ingress/egress_bytes` (not exposed by default) are Bytes;
  avg Kbps = (bytes × 8) / (bucket_seconds × 1000). Peak cannot be derived
  from bytes.

## Report red-flag thresholds (weekly report)

Surface these at the **top** of any report, flagged red (design doc sec.6):

- Any **P1 (critical)** alert in the period: count > 0.
- **ADEM overall score** dropped **> 10** points week-over-week.
- Any **SC/RN tunnel** currently down.
- Connected-user peak within ~10% of known licensed capacity (capacity note).
