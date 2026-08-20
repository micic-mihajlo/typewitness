# GitHub Action

TypeWitness can post one sticky pull request comment and leave existing
`text`, `json`, and `sarif` reporters unchanged.

```yaml
name: TypeWitness

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write

jobs:
  typewitness:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: micic-mihajlo/typewitness@main
        with:
          diff-ref: ${{ github.event.pull_request.base.sha }}
          blocking: "false"
```

Pin the action to a released tag. `blocking: "false"` keeps the comment
advisory. Set it to `"true"` if findings should fail the job.

The action writes `--format markdown` that starts with
`<!-- typewitness-report:v1 -->`. A later run updates that same comment.
A clean scan removes it.
