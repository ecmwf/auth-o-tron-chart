# Dashboard metric-name transition

Auth-O-Tron hard-renamed six emitted auth-domain metric families to the
`authotron_*` namespace. The chart still defaults to Auth-O-Tron 0.3.6, which
emits the legacy names, so dashboard queries select both names with an anchored
`__name__` matcher. This keeps panels populated for the default installation and
sums old and new series correctly during a mixed-version rollout.

Remove the legacy alternatives only after both `Chart.yaml`'s `appVersion` and
`values.yaml`'s `image.tag` have been bumped to a released image that emits the
prefixed names, and after the rollout transition is complete. A chart-version-
only bump, including the separately proposed 0.4.0 chart change in PR #13, is
not sufficient. PR #13's token-store removal remains independent of this
migration.

`scripts/validate-dashboard.py` asserts the six fallback pairs while 0.3.6 is
the default and rejects bare uses of either renamed or legacy metric names.
