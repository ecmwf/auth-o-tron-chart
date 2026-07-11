# Dashboard metric-name transition

Auth-O-Tron hard-renamed six emitted auth-domain metric families to the
`authotron_*` namespace. The chart still defaults to Auth-O-Tron 0.3.6, which
emits the legacy names. Each dashboard query therefore applies a new-first
per-series fallback, `rate(new{...}[...]) or rate(legacy{...}[...])`, before
aggregation. Both branches use identical label matchers, so new-only and legacy-
only pods are retained while a series exposed under both names is counted once.
Ratios apply the fallback independently to numerator and denominator. Histogram
fallbacks happen before `sum by (le, ...)`, preserving bucket and panel grouping.

Remove the legacy alternatives only after both `Chart.yaml`'s `appVersion` and
`values.yaml`'s `image.tag` have been bumped to a released image that emits the
prefixed names, and after the rollout transition is complete. A chart-version-
only bump, including the separately proposed 0.4.0 chart change in PR #13, is
not sufficient. PR #13's token-store removal remains independent of this
migration.

`scripts/validate-dashboard.py` asserts the six fallback pairs while 0.3.6 is
the default. It rejects `__name__` regex unions and bare, reversed, differently
labelled, or post-aggregation uses of renamed metrics; histogram fallbacks must
also preserve the `le` grouping.
