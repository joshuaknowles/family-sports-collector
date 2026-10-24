# Knowles Family Sports collector

Reads public Maine Hoops / Exposure tournament pages and posts the official
schedule and score rows to the family website's authenticated ingest endpoint.
The provider limits requests from the website's own server, so this runs here.

## One-time setup (about 3 minutes)

1. Open this repo on GitHub -> Add file -> Create new file.
2. Name it exactly: .github/workflows/collector.yml
3. Paste the entire contents of WORKFLOW.yml from this repo and commit.
4. Repo Settings -> Secrets and variables -> Actions -> New repository secret:
   name COLLECTOR_TOKEN, value = the token provided separately.
5. Actions tab -> enable workflows if asked. Use "Run workflow" once to test.

The workflow then runs every 5 minutes by itself. Nothing else is required.
