# Migration From Metta `cogames-agents`

The initial `cogames-agents` package source was copied from the Metta monorepo.
The package keeps the `cogames-agents` distribution name and
`cogames_agents` import path so existing policy URIs and class paths can keep
working after the source moves out of the monorepo.

Metta should consume this repo as an external policy package or leave it as an
optional install for workflows that need built-in scripted policies.
